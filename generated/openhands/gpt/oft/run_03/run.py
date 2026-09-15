import argparse
import json
import logging
import sys
from collections import deque
from dataclasses import dataclass
from typing import Optional

import simpy


MS = 1.0


def parse_hhmmss_to_ms(s: str) -> int:
    parts = s.strip().split(":")
    if len(parts) not in (3, 4):
        raise ValueError(f"Invalid time format: {s!r}")
    hh = int(parts[0])
    mm = int(parts[1])
    ss = int(parts[2])
    msec = int(parts[3]) if len(parts) == 4 else 0
    return ((hh * 3600 + mm * 60 + ss) * 1000) + msec


class Notifier:
    def __init__(self, env: simpy.Environment):
        self._env = env
        self._event = env.event()

    @property
    def event(self) -> simpy.Event:
        return self._event

    def trigger(self) -> None:
        if not self._event.triggered:
            self._event.succeed()
        self._event = self._env.event()


class Emitter:
    def __init__(self, env: simpy.Environment):
        self.env = env

    def emit(self, model: str, event_type: str, val: dict) -> None:
        obj = {
            "timestamp_ms": float(self.env.now),
            "model": model,
            "type": event_type,
            "val": val,
        }
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


@dataclass(frozen=True)
class DataPacket:
    seq: int
    bit: int


@dataclass(frozen=True)
class AckPacket:
    bit: int


class Subnet:
    def __init__(self, env: simpy.Environment, name: str, delay_ms: int, emitter: Optional[Emitter] = None):
        self.env = env
        self.name = name
        self.delay_ms = delay_ms
        self.inbox = simpy.Store(env)
        self.outbox = simpy.Store(env)
        self._proc = env.process(self._run())
        self._emitter = emitter

    def _run(self):
        while True:
            msg = yield self.inbox.get()
            yield self.env.timeout(self.delay_ms * MS)
            yield self.outbox.put(msg)


class Sender:
    def __init__(
        self,
        env: simpy.Environment,
        emitter: Emitter,
        data_out: simpy.Store,
        ack_in: simpy.Store,
    ):
        self.env = env
        self.emitter = emitter
        self.data_out = data_out
        self.ack_in = ack_in

        self._packets_remaining = 0
        self._next_seq = 1
        self._bit = 0

        self._control_notifier = Notifier(env)
        self._proc = env.process(self._run())

    def add_control(self, n: int) -> None:
        if n <= 0:
            return
        self._packets_remaining += int(n)
        self.emitter.emit(
            "sender",
            "control_cmd",
            {"added": int(n), "total_remaining": int(self._packets_remaining)},
        )
        self._control_notifier.trigger()

    def _wait_for_ack_or_timeout(self, expected_bit: int, timeout_ms: int):
        timeout_evt = self.env.timeout(timeout_ms * MS)
        while True:
            ack_evt = self.ack_in.get()
            res = yield simpy.AnyOf(self.env, [ack_evt, timeout_evt])
            if timeout_evt in res:
                return None
            ack = res[ack_evt]
            if isinstance(ack, AckPacket) and ack.bit == expected_bit:
                return ack

    def _run(self):
        while True:
            while self._packets_remaining <= 0:
                yield self._control_notifier.event

            seq = self._next_seq
            bit = self._bit

            self.emitter.emit("sender", "preparation_started", {"duration": 10000})
            yield self.env.timeout(10000 * MS)

            is_retry = False
            while True:
                self.emitter.emit(
                    "sender",
                    "packet_sent",
                    {"seq": int(seq), "bit": int(bit), "is_retry": bool(is_retry)},
                )
                yield self.data_out.put(DataPacket(seq=seq, bit=bit))

                ack = yield from self._wait_for_ack_or_timeout(expected_bit=bit, timeout_ms=20000)
                if ack is None:
                    self.emitter.emit("sender", "timeout", {"seq": int(seq)})
                    is_retry = True
                    continue

                self.emitter.emit("sender", "ack_received", {"bit": int(bit)})
                self._bit = 1 - self._bit
                self._next_seq += 1
                self._packets_remaining -= 1
                break


class ServerReceiver:
    def __init__(
        self,
        env: simpy.Environment,
        emitter: Emitter,
        data_in: simpy.Store,
        ack_out: simpy.Store,
        storage: deque,
        storage_notifier: Notifier,
    ):
        self.env = env
        self.emitter = emitter
        self.data_in = data_in
        self.ack_out = ack_out
        self.storage = storage
        self.storage_notifier = storage_notifier
        self._expected_bit = 0
        self._proc = env.process(self._run())

    def _run(self):
        while True:
            pkt = yield self.data_in.get()
            if not isinstance(pkt, DataPacket):
                continue

            self.emitter.emit(
                "server_receiver",
                "packet_received",
                {"seq": int(pkt.seq), "bit": int(pkt.bit)},
            )

            yield self.env.timeout(3000 * MS)

            if pkt.bit == self._expected_bit:
                ack_bit = pkt.bit
                yield self.ack_out.put(AckPacket(bit=ack_bit))
                self.emitter.emit(
                    "server_receiver",
                    "ack_sent_to_sender",
                    {"bit": int(ack_bit)},
                )
                self.storage.append({"seq": int(pkt.seq)})
                self.storage_notifier.trigger()
                self._expected_bit = 1 - self._expected_bit
            else:
                ack_bit = 1 - self._expected_bit
                yield self.ack_out.put(AckPacket(bit=ack_bit))
                self.emitter.emit(
                    "server_receiver",
                    "ack_sent_to_sender",
                    {"bit": int(ack_bit)},
                )


class ServerSender:
    def __init__(
        self,
        env: simpy.Environment,
        emitter: Emitter,
        data_out: simpy.Store,
        ack_in: simpy.Store,
        storage: deque,
        storage_notifier: Notifier,
    ):
        self.env = env
        self.emitter = emitter
        self.data_out = data_out
        self.ack_in = ack_in
        self.storage = storage
        self.storage_notifier = storage_notifier

        self._download_allowed = False
        self._download_notifier = Notifier(env)

        self._bit = 0
        self._proc = env.process(self._run())

    def set_download_allowed(self, allowed: bool) -> None:
        allowed = bool(allowed)
        if allowed == self._download_allowed:
            return
        self._download_allowed = allowed
        self.emitter.emit(
            "server_sender",
            "download_valve_change",
            {"allowed": bool(self._download_allowed)},
        )
        self._download_notifier.trigger()

    def _wait_for_ack(self, expected_bit: int):
        while True:
            ack = yield self.ack_in.get()
            if isinstance(ack, AckPacket) and ack.bit == expected_bit:
                return ack

    def _run(self):
        while True:
            while (not self._download_allowed) or (len(self.storage) == 0):
                yield simpy.AnyOf(self.env, [self._download_notifier.event, self.storage_notifier.event])

            item = self.storage.popleft()
            seq = int(item["seq"])
            bit = int(self._bit)

            self.emitter.emit(
                "server_sender",
                "packet_forwarded",
                {"seq": int(seq), "bit": int(bit)},
            )
            yield self.data_out.put(DataPacket(seq=seq, bit=bit))

            yield from self._wait_for_ack(expected_bit=bit)
            self.emitter.emit(
                "server_sender",
                "ack_received_from_receiver",
                {"bit": int(bit)},
            )
            self._bit = 1 - self._bit


class Receiver:
    def __init__(
        self,
        env: simpy.Environment,
        emitter: Emitter,
        data_in: simpy.Store,
        ack_out: simpy.Store,
    ):
        self.env = env
        self.emitter = emitter
        self.data_in = data_in
        self.ack_out = ack_out
        self._expected_bit = 0
        self._proc = env.process(self._run())

    def _run(self):
        while True:
            pkt = yield self.data_in.get()
            if not isinstance(pkt, DataPacket):
                continue

            if pkt.bit == self._expected_bit:
                self.emitter.emit(
                    "receiver",
                    "processing_started",
                    {"seq": int(pkt.seq), "duration": 10000},
                )
                yield self.env.timeout(10000 * MS)
                ack_bit = pkt.bit
                yield self.ack_out.put(AckPacket(bit=ack_bit))
                self.emitter.emit("receiver", "ack_sent", {"bit": int(ack_bit)})
                self._expected_bit = 1 - self._expected_bit
            else:
                ack_bit = 1 - self._expected_bit
                yield self.ack_out.put(AckPacket(bit=ack_bit))
                self.emitter.emit("receiver", "ack_sent", {"bit": int(ack_bit)})


def schedule_commands(
    env: simpy.Environment,
    sender: Sender,
    server_sender: ServerSender,
    commands: list[tuple[int, str, int]],
    logger: logging.Logger,
):
    def _proc(ts_ms: int, typ: str, val: int):
        if ts_ms < 0:
            return
        if ts_ms > env.now:
            yield env.timeout((ts_ms - env.now) * MS)
        if typ == "control":
            sender.add_control(val)
        elif typ == "request":
            server_sender.set_download_allowed(val == 1)
        else:
            logger.warning("Unknown command type %r", typ)

    for ts_ms, typ, val in commands:
        env.process(_proc(ts_ms, typ, val))


def read_commands_from_stdin(logger: logging.Logger) -> list[tuple[int, str, int]]:
    commands: list[tuple[int, str, int]] = []
    for raw in sys.stdin:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            time_s, typ, val_s = line.split()
            ts_ms = parse_hhmmss_to_ms(time_s)
            val = int(val_s)
            commands.append((ts_ms, typ, val))
        except Exception as e:
            logger.warning("Skipping invalid stdin line %r (%s)", line, e)
    commands.sort(key=lambda x: x[0])
    return commands


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="ABP Dropbox-like sync simulation (SimPy)")
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=10000_000.0,
        help="Simulation duration in milliseconds (default: 10000_000.0)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s:%(message)s")
    logger = logging.getLogger("sim")

    try:
        sim_end_ms = float(args.simulation_time)
    except Exception:
        logger.error("Invalid --simulation_time")
        return 2

    env = simpy.Environment(initial_time=0.0)
    emitter = Emitter(env)

    # Subnet A (upload): Sender -> A1 -> ServerReceiver, ServerReceiver -> A2 -> Sender
    a1 = Subnet(env, name="A1", delay_ms=3000)
    a2 = Subnet(env, name="A2", delay_ms=3000)

    # Subnet B (download): ServerSender -> B1 -> Receiver, Receiver -> B2 -> ServerSender
    b1 = Subnet(env, name="B1", delay_ms=3000)
    b2 = Subnet(env, name="B2", delay_ms=3000)

    storage: deque = deque()
    storage_notifier = Notifier(env)

    sender = Sender(env, emitter=emitter, data_out=a1.inbox, ack_in=a2.outbox)
    server_receiver = ServerReceiver(
        env,
        emitter=emitter,
        data_in=a1.outbox,
        ack_out=a2.inbox,
        storage=storage,
        storage_notifier=storage_notifier,
    )
    _ = server_receiver

    server_sender = ServerSender(
        env,
        emitter=emitter,
        data_out=b1.inbox,
        ack_in=b2.outbox,
        storage=storage,
        storage_notifier=storage_notifier,
    )

    receiver = Receiver(env, emitter=emitter, data_in=b1.outbox, ack_out=b2.inbox)
    _ = receiver

    commands = read_commands_from_stdin(logger)
    schedule_commands(env, sender, server_sender, commands, logger)

    env.run(until=sim_end_ms * MS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
