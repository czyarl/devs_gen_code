import argparse
import json
import sys
from collections import deque

import simpy


def parse_timestamp_to_ms(ts: str) -> int:
    parts = ts.strip().split(":")
    if len(parts) not in (3, 4):
        raise ValueError(f"Invalid timestamp: {ts}")
    hh = int(parts[0])
    mm = int(parts[1])
    ss = int(parts[2])
    mmm = int(parts[3]) if len(parts) == 4 else 0
    return (((hh * 60 + mm) * 60) + ss) * 1000 + mmm


class JsonlEmitter:
    def __init__(self, env: simpy.Environment):
        self.env = env

    def emit(self, model: str, typ: str, val: dict) -> None:
        obj = {
            "timestamp_ms": float(self.env.now),
            "model": model,
            "type": typ,
            "val": val,
        }
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


class Link:
    def __init__(self, env: simpy.Environment, delay_ms: float):
        self.env = env
        self.delay_ms = delay_ms
        self.inbox = simpy.Store(env)
        self.outbox = simpy.Store(env)
        self._proc = env.process(self._run())

    def _run(self):
        while True:
            msg = yield self.inbox.get()
            yield self.env.timeout(self.delay_ms)
            yield self.outbox.put(msg)


class Sender:
    def __init__(self, env: simpy.Environment, emitter: JsonlEmitter, data_out: Link, ack_in: Link):
        self.env = env
        self.emitter = emitter
        self.data_out = data_out
        self.ack_in = ack_in

        self.seq = 1
        self.bit = 0
        self.packets_remaining = 0

        self._wakeup = env.event()
        self._proc = env.process(self._run())

    def add_control(self, n: int) -> None:
        if n <= 0:
            return
        was_idle = self.packets_remaining <= 0
        self.packets_remaining += n
        self.emitter.emit(
            "sender",
            "control_cmd",
            {"added": int(n), "total_remaining": int(self.packets_remaining)},
        )
        if was_idle and not self._wakeup.triggered:
            self._wakeup.succeed()

    def _wait_for_expected_ack_or_timeout(self, expected_bit: int, timeout_ms: float):
        deadline = self.env.now + timeout_ms
        while True:
            remaining = deadline - self.env.now
            if remaining <= 0:
                return None
            ack_get = self.ack_in.outbox.get()
            timeout_evt = self.env.timeout(remaining)
            res = yield ack_get | timeout_evt
            if ack_get in res:
                ack = res[ack_get]
                if ack.get("kind") != "ack":
                    continue
                if int(ack.get("bit")) == int(expected_bit):
                    return ack
                continue
            return None

    def _send_packet(self, seq: int, bit: int, is_retry: bool) -> None:
        self.emitter.emit(
            "sender",
            "packet_sent",
            {"seq": int(seq), "bit": int(bit), "is_retry": bool(is_retry)},
        )
        self.data_out.inbox.put({"kind": "data", "seq": int(seq), "bit": int(bit)})

    def _run(self):
        while True:
            if self.packets_remaining <= 0:
                self._wakeup = self.env.event()
                yield self._wakeup
                continue

            self.emitter.emit(
                "sender", "preparation_started", {"duration": 10000}
            )
            yield self.env.timeout(10000)

            is_retry = False
            while True:
                self._send_packet(self.seq, self.bit, is_retry=is_retry)
                ack = yield from self._wait_for_expected_ack_or_timeout(
                    expected_bit=self.bit, timeout_ms=20000
                )
                if ack is None:
                    self.emitter.emit("sender", "timeout", {"seq": int(self.seq)})
                    is_retry = True
                    continue

                self.emitter.emit(
                    "sender", "ack_received", {"bit": int(ack["bit"])}
                )
                self.bit = 1 - int(self.bit)
                self.seq += 1
                self.packets_remaining -= 1
                break


class Server:
    def __init__(
        self,
        env: simpy.Environment,
        emitter: JsonlEmitter,
        data_in: Link,
        ack_out: Link,
        data_out: Link,
        ack_in: Link,
    ):
        self.env = env
        self.emitter = emitter

        self.data_in = data_in
        self.ack_out = ack_out
        self.data_out = data_out
        self.ack_in = ack_in

        self.storage = deque()
        self._storage_event = env.event()

        self.receiver = ServerReceiver(env, emitter, data_in, ack_out, self)
        self.sender = ServerSender(env, emitter, data_out, ack_in, self)

    def push_to_storage(self, seq: int) -> None:
        self.storage.append(int(seq))
        if not self._storage_event.triggered:
            self._storage_event.succeed()

    def wait_for_storage(self):
        if self.storage:
            return self.env.timeout(0)
        self._storage_event = self.env.event()
        return self._storage_event


class ServerReceiver:
    def __init__(
        self,
        env: simpy.Environment,
        emitter: JsonlEmitter,
        data_in: Link,
        ack_out: Link,
        server: Server,
    ):
        self.env = env
        self.emitter = emitter
        self.data_in = data_in
        self.ack_out = ack_out
        self.server = server

        self.expected_bit = 0
        self._proc = env.process(self._run())

    def _send_ack(self, bit: int) -> None:
        self.emitter.emit(
            "server_receiver", "ack_sent_to_sender", {"bit": int(bit)}
        )
        self.ack_out.inbox.put({"kind": "ack", "bit": int(bit)})

    def _run(self):
        while True:
            msg = yield self.data_in.outbox.get()
            if msg.get("kind") != "data":
                continue

            seq = int(msg.get("seq"))
            bit = int(msg.get("bit"))
            self.emitter.emit(
                "server_receiver", "packet_received", {"seq": seq, "bit": bit}
            )

            yield self.env.timeout(3000)

            if bit == int(self.expected_bit):
                self._send_ack(bit)
                self.server.push_to_storage(seq)
                self.expected_bit = 1 - int(self.expected_bit)
            else:
                prev_bit = 1 - int(self.expected_bit)
                self._send_ack(prev_bit)


class ServerSender:
    def __init__(
        self,
        env: simpy.Environment,
        emitter: JsonlEmitter,
        data_out: Link,
        ack_in: Link,
        server: Server,
    ):
        self.env = env
        self.emitter = emitter
        self.data_out = data_out
        self.ack_in = ack_in
        self.server = server

        self.download_allowed = False
        self._valve_event = env.event()

        self.bit = 0
        self._proc = env.process(self._run())

    def set_download_allowed(self, allowed: bool) -> None:
        allowed = bool(allowed)
        if allowed == self.download_allowed:
            return

        self.download_allowed = allowed
        self.emitter.emit(
            "server_sender", "download_valve_change", {"allowed": bool(allowed)}
        )
        if not self._valve_event.triggered:
            self._valve_event.succeed()

    def _wait_for_valve_change(self):
        self._valve_event = self.env.event()
        return self._valve_event

    def _run(self):
        while True:
            if not self.download_allowed:
                yield self._wait_for_valve_change()
                continue

            if not self.server.storage:
                yield self.server.wait_for_storage()
                continue

            seq = int(self.server.storage.popleft())
            bit = int(self.bit)

            self.emitter.emit(
                "server_sender", "packet_forwarded", {"seq": seq, "bit": bit}
            )
            self.data_out.inbox.put({"kind": "data", "seq": seq, "bit": bit})

            while True:
                ack = yield self.ack_in.outbox.get()
                if ack.get("kind") != "ack":
                    continue
                if int(ack.get("bit")) != bit:
                    continue
                self.emitter.emit(
                    "server_sender",
                    "ack_received_from_receiver",
                    {"bit": int(ack.get("bit"))},
                )
                self.bit = 1 - int(self.bit)
                break


class Receiver:
    def __init__(
        self,
        env: simpy.Environment,
        emitter: JsonlEmitter,
        data_in: Link,
        ack_out: Link,
    ):
        self.env = env
        self.emitter = emitter
        self.data_in = data_in
        self.ack_out = ack_out
        self._proc = env.process(self._run())

    def _run(self):
        while True:
            msg = yield self.data_in.outbox.get()
            if msg.get("kind") != "data":
                continue
            seq = int(msg.get("seq"))
            bit = int(msg.get("bit"))

            self.emitter.emit(
                "receiver",
                "processing_started",
                {"seq": seq, "duration": 10000},
            )
            yield self.env.timeout(10000)

            self.emitter.emit("receiver", "ack_sent", {"bit": bit})
            self.ack_out.inbox.put({"kind": "ack", "bit": bit})


def read_commands_from_stdin():
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"Invalid input line: {line}")
        ts_s, typ, val_s = parts
        at_ms = parse_timestamp_to_ms(ts_s)
        if typ not in ("control", "request"):
            raise ValueError(f"Invalid command type: {typ}")
        yield at_ms, typ, int(val_s)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Dropbox-like sync simulation with ABP")
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=10000_000.0,
        help="Simulation duration in milliseconds (simulation time)",
    )
    args = parser.parse_args(argv)

    simulation_time_ms = float(args.simulation_time)
    if simulation_time_ms < 0:
        simulation_time_ms = 0.0

    env = simpy.Environment()
    emitter = JsonlEmitter(env)

    # Subnets: reliable FIFO, fixed 3s delay
    a1 = Link(env, delay_ms=3000)  # Sender -> Server
    a2 = Link(env, delay_ms=3000)  # Server -> Sender
    b1 = Link(env, delay_ms=3000)  # Server -> Receiver
    b2 = Link(env, delay_ms=3000)  # Receiver -> Server

    sender = Sender(env, emitter, data_out=a1, ack_in=a2)
    server = Server(env, emitter, data_in=a1, ack_out=a2, data_out=b1, ack_in=b2)
    _receiver = Receiver(env, emitter, data_in=b1, ack_out=b2)

    def schedule_control(at_ms: int, n: int):
        yield env.timeout(max(0, at_ms - env.now))
        sender.add_control(n)

    def schedule_request(at_ms: int, val: int):
        yield env.timeout(max(0, at_ms - env.now))
        server.sender.set_download_allowed(bool(val))

    for at_ms, typ, val in read_commands_from_stdin():
        if at_ms > simulation_time_ms:
            continue
        if typ == "control":
            env.process(schedule_control(at_ms, val))
        else:
            env.process(schedule_request(at_ms, val))

    env.run(until=simulation_time_ms)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
