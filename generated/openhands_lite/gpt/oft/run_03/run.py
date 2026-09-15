import argparse
import json
import logging
import sys

import simpy


SUBNET_DELAY_MS = 3000.0
SENDER_PREP_MS = 10000.0
SENDER_TIMEOUT_MS = 20000.0
SERVER_RX_PROCESS_MS = 3000.0
RECEIVER_PROCESS_MS = 10000.0


def parse_hhmmss_to_ms(s: str) -> float:
    parts = s.strip().split(":")
    if len(parts) not in (3, 4):
        raise ValueError(f"Invalid timestamp '{s}'")
    hh = int(parts[0])
    mm = int(parts[1])
    ss = int(parts[2])
    msec = int(parts[3]) if len(parts) == 4 else 0
    return float((((hh * 60) + mm) * 60 + ss) * 1000 + msec)


class EventSink:
    def __init__(self, env: simpy.Environment):
        self.env = env

    def emit(self, model: str, typ: str, val: dict) -> None:
        obj = {
            "timestamp_ms": float(self.env.now),
            "model": model,
            "type": typ,
            "val": val,
        }
        print(json.dumps(obj), file=sys.stdout, flush=True)


class SubnetFIFO:
    def __init__(self, env: simpy.Environment, delay_ms: float):
        self.env = env
        self.delay_ms = float(delay_ms)
        self._in = simpy.Store(env)
        self.out = simpy.Store(env)
        self.env.process(self._run())

    def send(self, msg: dict) -> None:
        self._in.put(msg)

    def _run(self):
        while True:
            msg = yield self._in.get()
            yield self.env.timeout(self.delay_ms)
            yield self.out.put(msg)


class Sender:
    def __init__(self, env: simpy.Environment, sink: EventSink, uplink: SubnetFIFO, downlink: SubnetFIFO):
        self.env = env
        self.sink = sink
        self.uplink = uplink
        self.downlink = downlink

        self.total_packets_to_send = 0
        self.seq = 1
        self.bit = 0

        self._wake = env.event()

        # Buffer ACKs so we never lose them on timeout races.
        self._ack_inbox = simpy.Store(env)
        self.env.process(self._ack_listener())
        self.env.process(self._run())

    def control(self, n: int) -> None:
        if n <= 0:
            return
        was_idle = self.total_packets_to_send == 0
        self.total_packets_to_send += int(n)
        self.sink.emit(
            "sender",
            "control_cmd",
            {"added": int(n), "total_remaining": int(self.total_packets_to_send)},
        )
        if was_idle and not self._wake.triggered:
            self._wake.succeed()

    def _ack_listener(self):
        while True:
            msg = yield self.downlink.out.get()
            if msg.get("kind") == "ack":
                yield self._ack_inbox.put(msg)

    def _wait_for_ack_bit(self, desired_bit: int, timeout_ms: float) -> bool:
        deadline = float(self.env.now) + float(timeout_ms)
        while True:
            remaining = deadline - float(self.env.now)
            if remaining <= 0:
                return False

            recv_ev = self._ack_inbox.get()
            timeout_ev = self.env.timeout(remaining)
            res = yield recv_ev | timeout_ev

            if timeout_ev in res:
                if hasattr(recv_ev, "cancel"):
                    recv_ev.cancel()
                return False

            if hasattr(timeout_ev, "cancel"):
                timeout_ev.cancel()

            msg = res[recv_ev]
            if int(msg.get("bit")) == int(desired_bit):
                return True

    def _run(self):
        while True:
            while self.total_packets_to_send <= 0:
                self._wake = self.env.event()
                yield self._wake

            self.sink.emit("sender", "preparation_started", {"duration": int(SENDER_PREP_MS)})
            yield self.env.timeout(SENDER_PREP_MS)

            while self.total_packets_to_send > 0:
                is_retry = False
                while True:
                    self.sink.emit(
                        "sender",
                        "packet_sent",
                        {"seq": int(self.seq), "bit": int(self.bit), "is_retry": bool(is_retry)},
                    )
                    self.uplink.send({"kind": "data", "seq": int(self.seq), "bit": int(self.bit)})

                    ok = yield from self._wait_for_ack_bit(self.bit, SENDER_TIMEOUT_MS)
                    if ok:
                        self.sink.emit("sender", "ack_received", {"bit": int(self.bit)})
                        self.bit = 1 - int(self.bit)
                        self.seq += 1
                        self.total_packets_to_send -= 1
                        break

                    self.sink.emit("sender", "timeout", {"seq": int(self.seq)})
                    is_retry = True


class ServerReceiver:
    def __init__(self, env: simpy.Environment, sink: EventSink, uplink: SubnetFIFO, downlink: SubnetFIFO, storage: simpy.Store, on_storage_put):
        self.env = env
        self.sink = sink
        self.uplink = uplink  # A2 (server -> sender)
        self.downlink = downlink  # A1 (sender -> server)
        self.storage = storage
        self.on_storage_put = on_storage_put

        self.expected_bit = 0
        self.env.process(self._run())

    def _run(self):
        while True:
            msg = yield self.downlink.out.get()
            if msg.get("kind") != "data":
                continue
            seq = int(msg.get("seq"))
            bit = int(msg.get("bit"))
            self.sink.emit("server_receiver", "packet_received", {"seq": seq, "bit": bit})

            yield self.env.timeout(SERVER_RX_PROCESS_MS)

            if bit == int(self.expected_bit):
                ack_bit = bit
                self.uplink.send({"kind": "ack", "bit": ack_bit})
                self.sink.emit("server_receiver", "ack_sent_to_sender", {"bit": int(ack_bit)})

                yield self.storage.put({"seq": seq})
                self.on_storage_put()
                self.expected_bit = 1 - int(self.expected_bit)
            else:
                ack_bit = 1 - int(self.expected_bit)
                self.uplink.send({"kind": "ack", "bit": ack_bit})
                self.sink.emit("server_receiver", "ack_sent_to_sender", {"bit": int(ack_bit)})


class ServerSender:
    def __init__(self, env: simpy.Environment, sink: EventSink, uplink: SubnetFIFO, downlink: SubnetFIFO, storage: simpy.Store):
        self.env = env
        self.sink = sink
        self.uplink = uplink  # B1 (server -> receiver)
        self.downlink = downlink  # B2 (receiver -> server)
        self.storage = storage

        self.download_allowed = False
        self.bit = 0
        self.waiting_for_ack = False

        self._state = env.event()
        self.env.process(self._run())
        self.env.process(self._listen_for_acks())

    def notify_state_change(self) -> None:
        if not self._state.triggered:
            self._state.succeed()

    def set_download_allowed(self, allowed: bool) -> None:
        self.download_allowed = bool(allowed)
        self.sink.emit("server_sender", "download_valve_change", {"allowed": bool(self.download_allowed)})
        self.notify_state_change()

    def _listen_for_acks(self):
        while True:
            msg = yield self.downlink.out.get()
            if msg.get("kind") != "ack":
                continue
            bit = int(msg.get("bit"))
            if self.waiting_for_ack and bit == int(self.bit):
                self.sink.emit("server_sender", "ack_received_from_receiver", {"bit": bit})
                self.bit = 1 - int(self.bit)
                self.waiting_for_ack = False
                self.notify_state_change()

    def _run(self):
        while True:
            while not (self.download_allowed and (not self.waiting_for_ack) and len(self.storage.items) > 0):
                self._state = self.env.event()
                yield self._state

            item = yield self.storage.get()
            seq = int(item.get("seq"))
            bit = int(self.bit)
            self.waiting_for_ack = True

            self.sink.emit("server_sender", "packet_forwarded", {"seq": seq, "bit": bit})
            self.uplink.send({"kind": "data", "seq": seq, "bit": bit})


class Receiver:
    def __init__(self, env: simpy.Environment, sink: EventSink, uplink: SubnetFIFO, downlink: SubnetFIFO):
        self.env = env
        self.sink = sink
        self.uplink = uplink  # B2 (receiver -> server)
        self.downlink = downlink  # B1 (server -> receiver)

        self.expected_bit = 0
        self.env.process(self._run())

    def _run(self):
        while True:
            msg = yield self.downlink.out.get()
            if msg.get("kind") != "data":
                continue
            seq = int(msg.get("seq"))
            bit = int(msg.get("bit"))

            if bit != int(self.expected_bit):
                ack_bit = 1 - int(self.expected_bit)
                self.uplink.send({"kind": "ack", "bit": ack_bit})
                self.sink.emit("receiver", "ack_sent", {"bit": int(ack_bit)})
                continue

            self.sink.emit(
                "receiver",
                "processing_started",
                {"seq": seq, "duration": int(RECEIVER_PROCESS_MS)},
            )
            yield self.env.timeout(RECEIVER_PROCESS_MS)

            self.uplink.send({"kind": "ack", "bit": bit})
            self.sink.emit("receiver", "ack_sent", {"bit": int(bit)})
            self.expected_bit = 1 - int(self.expected_bit)


def schedule_commands(env: simpy.Environment, sink: EventSink, sender: Sender, server_sender: ServerSender, lines: list[str], sim_time_ms: float):
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) != 3:
            raise ValueError(f"Invalid input line: {line}")
        ts_s, typ, val_s = parts
        t_ms = parse_hhmmss_to_ms(ts_s)
        if t_ms > sim_time_ms:
            continue

        if typ == "control":
            n = int(val_s)

            def _proc_control(at_ms: float, amount: int):
                yield env.timeout(max(0.0, at_ms - float(env.now)))
                sender.control(amount)

            env.process(_proc_control(t_ms, n))
        elif typ == "request":
            allowed = bool(int(val_s))

            def _proc_request(at_ms: float, a: bool):
                yield env.timeout(max(0.0, at_ms - float(env.now)))
                server_sender.set_download_allowed(a)

            env.process(_proc_request(t_ms, allowed))
        else:
            raise ValueError(f"Unknown command type '{typ}'")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=10000_000.0,
        help="Simulation duration in milliseconds (simulation time)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(levelname)s: %(message)s")

    sim_time_ms = float(args.simulation_time)
    if sim_time_ms < 0:
        raise SystemExit("--simulation_time must be non-negative")

    lines = [ln for ln in sys.stdin]

    env = simpy.Environment()
    sink = EventSink(env)

    a1 = SubnetFIFO(env, SUBNET_DELAY_MS)  # sender -> server
    a2 = SubnetFIFO(env, SUBNET_DELAY_MS)  # server -> sender
    b1 = SubnetFIFO(env, SUBNET_DELAY_MS)  # server -> receiver
    b2 = SubnetFIFO(env, SUBNET_DELAY_MS)  # receiver -> server

    storage = simpy.Store(env)

    server_sender = ServerSender(env, sink, uplink=b1, downlink=b2, storage=storage)
    sender = Sender(env, sink, uplink=a1, downlink=a2)

    def on_storage_put():
        server_sender.notify_state_change()

    _server_receiver = ServerReceiver(env, sink, uplink=a2, downlink=a1, storage=storage, on_storage_put=on_storage_put)
    _receiver = Receiver(env, sink, uplink=b2, downlink=b1)

    schedule_commands(env, sink, sender, server_sender, lines, sim_time_ms)

    env.run(until=sim_time_ms)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
