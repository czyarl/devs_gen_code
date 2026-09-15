#!/usr/bin/env python3
import argparse
import sys
import json
import logging
from collections import deque
import random  # allowed; not required for deterministic behavior
import simpy

# Requirement mentions xdevs; import if available.
try:
    import xdevs  # type: ignore  # noqa: F401
except Exception:  # pragma: no cover
    xdevs = None  # noqa: F841


# -----------------------------
# Constants (all in milliseconds)
# -----------------------------
PREPARATION_MS = 10_000.0
SUBNET_DELAY_MS = 3_000.0
SERVER_RECEIVER_PROCESS_MS = 3_000.0
RECEIVER_PROCESS_MS = 10_000.0
SENDER_TIMEOUT_MS = 20_000.0


# -----------------------------
# JSONL event emission
# -----------------------------
class EventStream:
    def __init__(self, env: simpy.Environment):
        self.env = env

    def emit(self, model: str, etype: str, val: dict):
        obj = {
            "timestamp_ms": float(self.env.now),
            "model": model,
            "type": etype,
            "val": val,
        }
        # stdout MUST contain ONLY JSONL events
        print(json.dumps(obj), flush=True)


# -----------------------------
# Message types
# -----------------------------
class DataPacket:
    __slots__ = ("seq", "bit")

    def __init__(self, seq: int, bit: int):
        self.seq = int(seq)
        self.bit = int(bit)


class Ack:
    __slots__ = ("bit",)

    def __init__(self, bit: int):
        self.bit = int(bit)


# -----------------------------
# Subnet (reliable FIFO, fixed delay)
# -----------------------------
class Subnet:
    def __init__(self, env: simpy.Environment, name: str, delay_ms: float, log: logging.Logger):
        self.env = env
        self.name = name
        self.delay_ms = float(delay_ms)
        self.log = log

        self.in_store = simpy.Store(env)
        self.out_store = simpy.Store(env)

        self.env.process(self._run())

    def _run(self):
        while True:
            msg = yield self.in_store.get()
            yield self.env.timeout(self.delay_ms)
            yield self.out_store.put(msg)


# -----------------------------
# Sender (Uploader) with ABP
# -----------------------------
class Sender:
    def __init__(
        self,
        env: simpy.Environment,
        events: EventStream,
        data_out: simpy.Store,
        ack_in: simpy.Store,
        log: logging.Logger,
    ):
        self.env = env
        self.events = events
        self.data_out = data_out
        self.ack_in = ack_in
        self.log = log

        self.packets_remaining = 0
        self.seq = 1
        self.bit = 0

        self._wake_event = env.event()
        self.env.process(self._run())

    def add_control(self, n: int):
        n = int(n)
        if n <= 0:
            return
        self.packets_remaining += n
        self.events.emit(
            "sender",
            "control_cmd",
            {"added": n, "total_remaining": int(self.packets_remaining)},
        )
        if not self._wake_event.triggered:
            self._wake_event.succeed()

    def _wait_until_woken(self):
        if self.packets_remaining > 0:
            return self.env.timeout(0)
        # create a new wake event and wait on it
        self._wake_event = self.env.event()
        return self._wake_event

    def _wait_for_correct_ack_or_timeout(self, expected_bit: int):
        deadline = self.env.now + SENDER_TIMEOUT_MS
        while True:
            remaining = deadline - self.env.now
            if remaining <= 0:
                return None  # timeout

            ack_get_ev = self.ack_in.get()
            timeout_ev = self.env.timeout(remaining)
            res = yield self.env.any_of({ack_get_ev, timeout_ev})
            if timeout_ev in res:
                return None  # timeout
            ack = res[ack_get_ev]
            if isinstance(ack, Ack) and ack.bit == expected_bit:
                return ack
            # Wrong/duplicate ACK: ignore and keep waiting until deadline

    def _run(self):
        while True:
            # Idle wait
            yield self._wait_until_woken()

            # Work through queue
            while self.packets_remaining > 0:
                # Preparation before sending a NEW packet (not a retransmission)
                self.events.emit("sender", "preparation_started", {"duration": int(PREPARATION_MS)})
                yield self.env.timeout(PREPARATION_MS)

                current_seq = self.seq
                current_bit = self.bit

                is_retry = False
                while True:
                    # send (or retransmit) packet
                    pkt = DataPacket(current_seq, current_bit)
                    self.events.emit(
                        "sender",
                        "packet_sent",
                        {"seq": int(current_seq), "bit": int(current_bit), "is_retry": bool(is_retry)},
                    )
                    yield self.data_out.put(pkt)

                    ack = yield from self._wait_for_correct_ack_or_timeout(current_bit)
                    if ack is None:
                        self.events.emit("sender", "timeout", {"seq": int(current_seq)})
                        is_retry = True
                        continue

                    self.events.emit("sender", "ack_received", {"bit": int(ack.bit)})
                    break

                # success: next packet
                self.seq += 1
                self.bit = 1 - self.bit
                self.packets_remaining -= 1


# -----------------------------
# ServerReceiver (ingress) with ABP + storage enqueue
# -----------------------------
class ServerReceiver:
    def __init__(
        self,
        env: simpy.Environment,
        events: EventStream,
        data_in: simpy.Store,
        ack_out: simpy.Store,
        storage_queue: simpy.Store,
        notify_storage_cb,
        log: logging.Logger,
    ):
        self.env = env
        self.events = events
        self.data_in = data_in
        self.ack_out = ack_out
        self.storage_queue = storage_queue
        self.notify_storage_cb = notify_storage_cb
        self.log = log

        self.expected_bit = 0
        self.env.process(self._run())

    def _run(self):
        while True:
            pkt = yield self.data_in.get()
            if not isinstance(pkt, DataPacket):
                continue

            self.events.emit("server_receiver", "packet_received", {"seq": int(pkt.seq), "bit": int(pkt.bit)})
            yield self.env.timeout(SERVER_RECEIVER_PROCESS_MS)

            if pkt.bit == self.expected_bit:
                # correct, in-order
                ack = Ack(pkt.bit)
                self.events.emit("server_receiver", "ack_sent_to_sender", {"bit": int(ack.bit)})
                yield self.ack_out.put(ack)

                yield self.storage_queue.put(pkt)
                self.notify_storage_cb()

                self.expected_bit = 1 - self.expected_bit
            else:
                # duplicate/out-of-order: resend last ACK (bit = 1 - expected_bit)
                prev_bit = 1 - self.expected_bit
                ack = Ack(prev_bit)
                self.events.emit("server_receiver", "ack_sent_to_sender", {"bit": int(ack.bit)})
                yield self.ack_out.put(ack)


# -----------------------------
# ServerSender (egress) with ABP gate by download_allowed
# -----------------------------
class ServerSender:
    def __init__(
        self,
        env: simpy.Environment,
        events: EventStream,
        storage_queue: simpy.Store,
        data_out: simpy.Store,
        ack_in: simpy.Store,
        log: logging.Logger,
    ):
        self.env = env
        self.events = events
        self.storage_queue = storage_queue
        self.data_out = data_out
        self.ack_in = ack_in
        self.log = log

        self.download_allowed = False
        self._trigger = env.event()

        self.waiting_for_ack = False
        self.current_bit = None

        self.env.process(self._run())

    def notify(self):
        if not self._trigger.triggered:
            self._trigger.succeed()

    def set_download_allowed(self, allowed: bool):
        self.download_allowed = bool(allowed)
        self.events.emit("server_sender", "download_valve_change", {"allowed": bool(self.download_allowed)})
        self.notify()

    def _wait_for_correct_ack(self, expected_bit: int):
        while True:
            ack = yield self.ack_in.get()
            if isinstance(ack, Ack) and ack.bit == expected_bit:
                return ack
            # Ignore other/duplicate acks

    def _run(self):
        while True:
            # If waiting for ACK, complete current cycle regardless of valve.
            if self.waiting_for_ack:
                ack = yield from self._wait_for_correct_ack(self.current_bit)
                self.events.emit("server_sender", "ack_received_from_receiver", {"bit": int(ack.bit)})
                self.waiting_for_ack = False
                self.current_bit = None
                continue

            # Not waiting: can start a new transfer only if allowed and data exists.
            if self.download_allowed and len(self.storage_queue.items) > 0:
                pkt = yield self.storage_queue.get()
                if not isinstance(pkt, DataPacket):
                    continue

                self.events.emit("server_sender", "packet_forwarded", {"seq": int(pkt.seq), "bit": int(pkt.bit)})
                yield self.data_out.put(pkt)
                self.waiting_for_ack = True
                self.current_bit = int(pkt.bit)
                continue

            # Otherwise wait for a trigger (valve change or storage arrival)
            self._trigger = self.env.event()
            yield self._trigger


# -----------------------------
# Receiver (Downloader)
# -----------------------------
class Receiver:
    def __init__(
        self,
        env: simpy.Environment,
        events: EventStream,
        data_in: simpy.Store,
        ack_out: simpy.Store,
        log: logging.Logger,
    ):
        self.env = env
        self.events = events
        self.data_in = data_in
        self.ack_out = ack_out
        self.log = log

        self.env.process(self._run())

    def _run(self):
        while True:
            pkt = yield self.data_in.get()
            if not isinstance(pkt, DataPacket):
                continue

            self.events.emit("receiver", "processing_started", {"seq": int(pkt.seq), "duration": int(RECEIVER_PROCESS_MS)})
            yield self.env.timeout(RECEIVER_PROCESS_MS)

            ack = Ack(pkt.bit)
            self.events.emit("receiver", "ack_sent", {"bit": int(ack.bit)})
            yield self.ack_out.put(ack)


# -----------------------------
# Input parsing and scheduling
# -----------------------------
def parse_time_to_ms(t: str) -> float:
    """
    Accepts:
      HH:MM:SS
      HH:MM:SS:mmm
    Returns milliseconds as float.
    """
    parts = t.strip().split(":")
    if len(parts) not in (3, 4):
        raise ValueError(f"Invalid time format: {t}")

    hh = int(parts[0])
    mm = int(parts[1])
    ss = int(parts[2])
    msec = int(parts[3]) if len(parts) == 4 else 0
    return float((((hh * 60 + mm) * 60 + ss) * 1000) + msec)


def read_commands(stdin) -> list[tuple[float, str, int]]:
    cmds = []
    for raw in stdin:
        line = raw.strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) != 3:
            raise ValueError(f"Invalid command line (expected 3 fields): {line}")
        t_s, typ, val_s = fields
        t_ms = parse_time_to_ms(t_s)
        if typ not in ("control", "request"):
            raise ValueError(f"Unknown command type: {typ}")
        val = int(val_s)
        cmds.append((t_ms, typ, val))
    cmds.sort(key=lambda x: x[0])
    return cmds


def schedule_commands(env: simpy.Environment, cmds, sender: Sender, server_sender: ServerSender, log: logging.Logger):
    def proc():
        for t_ms, typ, val in cmds:
            if t_ms < env.now:
                # If input is unsorted or time went backwards, apply immediately
                delay = 0.0
            else:
                delay = t_ms - env.now
            yield env.timeout(delay)

            if typ == "control":
                sender.add_control(val)
            elif typ == "request":
                server_sender.set_download_allowed(bool(val))

    env.process(proc())


# -----------------------------
# Main
# -----------------------------
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Dropbox-like sync simulation with two ABP loops.")
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=10_000_000.0,
        help="Simulation duration in milliseconds (simulation time). Default: 10000_000.0",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    log = logging.getLogger("sim")

    env = simpy.Environment()
    events = EventStream(env)

    # Build network subnets
    subnet_a1 = Subnet(env, "A1", SUBNET_DELAY_MS, log)  # Sender -> Server
    subnet_a2 = Subnet(env, "A2", SUBNET_DELAY_MS, log)  # Server -> Sender (ACK)
    subnet_b1 = Subnet(env, "B1", SUBNET_DELAY_MS, log)  # Server -> Receiver
    subnet_b2 = Subnet(env, "B2", SUBNET_DELAY_MS, log)  # Receiver -> Server (ACK)

    # Shared server storage
    storage_queue = simpy.Store(env)

    # Components
    server_sender = ServerSender(
        env=env,
        events=events,
        storage_queue=storage_queue,
        data_out=subnet_b1.in_store,
        ack_in=subnet_b2.out_store,
        log=log,
    )

    server_receiver = ServerReceiver(
        env=env,
        events=events,
        data_in=subnet_a1.out_store,
        ack_out=subnet_a2.in_store,
        storage_queue=storage_queue,
        notify_storage_cb=server_sender.notify,
        log=log,
    )

    sender = Sender(
        env=env,
        events=events,
        data_out=subnet_a1.in_store,
        ack_in=subnet_a2.out_store,
        log=log,
    )

    receiver = Receiver(
        env=env,
        events=events,
        data_in=subnet_b1.out_store,
        ack_out=subnet_b2.in_store,
        log=log,
    )

    # Read and schedule stdin commands
    try:
        cmds = read_commands(sys.stdin)
    except Exception as e:
        log.error("Failed to read commands from stdin: %s", e)
        return 2

    schedule_commands(env, cmds, sender, server_sender, log)

    # Run simulation
    sim_until = float(args.simulation_time)
    if sim_until < 0:
        sim_until = 0.0

    env.run(until=sim_until)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())