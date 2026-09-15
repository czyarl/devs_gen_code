#!/usr/bin/env python3
"""Discrete-event simulation of a Dropbox-like sync flow using two ABP loops.

Entry point: python run.py

Stdout: JSONL event stream (only).
Stderr: logs/debug.

Implements:
- Loop 1: Sender -> SubnetA -> ServerReceiver -> SubnetA(back) -> Sender
- Loop 2: ServerSender -> SubnetB -> Receiver -> SubnetB(back) -> ServerSender

All time units are milliseconds of simulation time.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import simpy


def parse_timestamp_to_ms(ts: str) -> float:
    """Parse timestamps HH:MM:SS or HH:MM:SS:mmm into milliseconds."""

    ts = ts.strip()
    parts = ts.split(":")
    if len(parts) not in (3, 4):
        raise ValueError(f"Invalid timestamp format: {ts!r}")

    try:
        hh = int(parts[0])
        mm = int(parts[1])
        ss = int(parts[2])
        mmm = int(parts[3]) if len(parts) == 4 else 0
    except ValueError as e:
        raise ValueError(f"Invalid timestamp number in {ts!r}") from e

    if not (0 <= mm < 60 and 0 <= ss < 60 and 0 <= mmm < 1000 and hh >= 0):
        raise ValueError(f"Out-of-range timestamp: {ts!r}")

    return float((((hh * 60) + mm) * 60 + ss) * 1000 + mmm)


class EventLogger:
    """JSONL logger: write required events to stdout only."""

    def __init__(self, env: simpy.Environment):
        self.env = env

    def emit(self, model: str, typ: str, val: Dict[str, Any]) -> None:
        print(
            json.dumps(
                {
                    "timestamp_ms": float(self.env.now),
                    "model": model,
                    "type": typ,
                    "val": val,
                }
            ),
            flush=True,
        )


@dataclass(frozen=True)
class Packet:
    seq: int
    bit: int


@dataclass(frozen=True)
class Ack:
    bit: int


class DelayChannel:
    """Reliable FIFO channel with fixed delay (ms)."""

    def __init__(self, env: simpy.Environment, delay_ms: float):
        self.env = env
        self.delay_ms = float(delay_ms)
        self.inbox: simpy.Store = simpy.Store(env)
        self.outbox: simpy.Store = simpy.Store(env)
        env.process(self._run())

    def _run(self):
        while True:
            item = yield self.inbox.get()
            yield self.env.timeout(self.delay_ms)
            yield self.outbox.put(item)


class Sender:
    PREP_MS = 10_000.0
    TIMEOUT_MS = 20_000.0

    def __init__(self, env: simpy.Environment, logger: EventLogger, data_out: simpy.Store, ack_in: simpy.Store):
        self.env = env
        self.log = logger
        self.data_out = data_out
        self.ack_in = ack_in

        self.packets_remaining = 0
        self.next_seq = 1
        self.bit = 0
        self._wakeup = simpy.Event(env)

        env.process(self._run())

    def add_control(self, n: int) -> None:
        if n <= 0:
            return
        self.packets_remaining += int(n)
        self.log.emit(
            "sender",
            "control_cmd",
            {"added": int(n), "total_remaining": int(self.packets_remaining)},
        )
        if not self._wakeup.triggered:
            self._wakeup.succeed()
        self._wakeup = simpy.Event(self.env)

    def _wait_for_correct_ack(self, expected_bit: int):
        start = self.env.now
        remaining = self.TIMEOUT_MS
        while remaining > 0:
            ack_get = self.ack_in.get()
            timeout_evt = self.env.timeout(remaining)
            res = yield simpy.events.AnyOf(self.env, [ack_get, timeout_evt])
            # In SimPy, AnyOf returns a dict-like mapping {event: value}
            if timeout_evt in res:
                return False
            ack: Ack = res[ack_get]
            if ack.bit == expected_bit:
                self.log.emit("sender", "ack_received", {"bit": int(ack.bit)})
                return True
            elapsed = self.env.now - start
            remaining = self.TIMEOUT_MS - elapsed
        return False

    def _run(self):
        while True:
            if self.packets_remaining <= 0:
                yield self._wakeup
                continue

            self.log.emit("sender", "preparation_started", {"duration": int(self.PREP_MS)})
            yield self.env.timeout(self.PREP_MS)

            seq = self.next_seq
            bit = self.bit
            is_retry = False

            while True:
                yield self.data_out.put(Packet(seq=seq, bit=bit))
                self.log.emit(
                    "sender",
                    "packet_sent",
                    {"seq": int(seq), "bit": int(bit), "is_retry": bool(is_retry)},
                )

                ok = yield from self._wait_for_correct_ack(expected_bit=bit)
                if ok:
                    self.packets_remaining -= 1
                    self.next_seq += 1
                    self.bit = 1 - self.bit
                    break

                self.log.emit("sender", "timeout", {"seq": int(seq)})
                is_retry = True


class ServerReceiver:
    PROCESS_MS = 3_000.0

    def __init__(
        self,
        env: simpy.Environment,
        logger: EventLogger,
        data_in: simpy.Store,
        ack_out: simpy.Store,
        storage_queue: simpy.Store,
        on_storage_put=None,
    ):
        self.env = env
        self.log = logger
        self.data_in = data_in
        self.ack_out = ack_out
        self.storage_queue = storage_queue
        self.on_storage_put = on_storage_put
        self.expected_bit = 0
        env.process(self._run())

    def _run(self):
        while True:
            pkt: Packet = yield self.data_in.get()
            self.log.emit("server_receiver", "packet_received", {"seq": int(pkt.seq), "bit": int(pkt.bit)})
            yield self.env.timeout(self.PROCESS_MS)

            if pkt.bit == self.expected_bit:
                # Correct packet
                yield self.ack_out.put(Ack(bit=pkt.bit))
                self.log.emit("server_receiver", "ack_sent_to_sender", {"bit": int(pkt.bit)})

                yield self.storage_queue.put({"seq": int(pkt.seq)})
                if self.on_storage_put is not None:
                    self.on_storage_put()

                self.expected_bit = 1 - self.expected_bit
            else:
                # Duplicate/unexpected -> resend previous ACK
                prev_bit = 1 - self.expected_bit
                yield self.ack_out.put(Ack(bit=prev_bit))
                self.log.emit("server_receiver", "ack_sent_to_sender", {"bit": int(prev_bit)})


class ServerSender:
    def __init__(
        self,
        env: simpy.Environment,
        logger: EventLogger,
        storage_queue: simpy.Store,
        data_out: simpy.Store,
        ack_in: simpy.Store,
    ):
        self.env = env
        self.log = logger
        self.storage_queue = storage_queue
        self.data_out = data_out
        self.ack_in = ack_in

        self.download_allowed = False
        self.bit = 0
        self._wakeup = simpy.Event(env)
        env.process(self._run())

    def notify(self) -> None:
        if not self._wakeup.triggered:
            self._wakeup.succeed()
        self._wakeup = simpy.Event(self.env)

    def set_download_allowed(self, allowed: bool) -> None:
        allowed = bool(allowed)
        if allowed == self.download_allowed:
            return
        self.download_allowed = allowed
        self.log.emit("server_sender", "download_valve_change", {"allowed": bool(self.download_allowed)})
        self.notify()

    def _wait_for_ack(self, expected_bit: int):
        while True:
            ack: Ack = yield self.ack_in.get()
            if ack.bit == expected_bit:
                self.log.emit("server_sender", "ack_received_from_receiver", {"bit": int(ack.bit)})
                return

    def _run(self):
        while True:
            while not self.download_allowed or len(self.storage_queue.items) == 0:
                yield self._wakeup

            payload = yield self.storage_queue.get()
            seq = int(payload["seq"])
            bit = int(self.bit)

            yield self.data_out.put(Packet(seq=seq, bit=bit))
            self.log.emit("server_sender", "packet_forwarded", {"seq": int(seq), "bit": int(bit)})

            # Finish current packet-ACK cycle even if valve turns off
            yield from self._wait_for_ack(expected_bit=bit)
            self.bit = 1 - self.bit


class Receiver:
    PROCESS_MS = 10_000.0

    def __init__(self, env: simpy.Environment, logger: EventLogger, data_in: simpy.Store, ack_out: simpy.Store):
        self.env = env
        self.log = logger
        self.data_in = data_in
        self.ack_out = ack_out
        self.expected_bit = 0
        env.process(self._run())

    def _run(self):
        while True:
            pkt: Packet = yield self.data_in.get()

            if pkt.bit == self.expected_bit:
                self.log.emit(
                    "receiver",
                    "processing_started",
                    {"seq": int(pkt.seq), "duration": int(self.PROCESS_MS)},
                )
                yield self.env.timeout(self.PROCESS_MS)
                yield self.ack_out.put(Ack(bit=pkt.bit))
                self.log.emit("receiver", "ack_sent", {"bit": int(pkt.bit)})
                self.expected_bit = 1 - self.expected_bit
            else:
                prev_bit = 1 - self.expected_bit
                yield self.ack_out.put(Ack(bit=prev_bit))
                self.log.emit("receiver", "ack_sent", {"bit": int(prev_bit)})


def read_stdin_commands() -> List[Tuple[float, str, int]]:
    cmds: List[Tuple[float, str, int]] = []
    for raw in sys.stdin:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"Invalid input line: {line!r}")
        t_ms = parse_timestamp_to_ms(parts[0])
        typ = parts[1]
        val = int(parts[2])
        if typ not in ("control", "request"):
            raise ValueError(f"Unknown command type: {typ!r}")
        cmds.append((t_ms, typ, val))

    cmds.sort(key=lambda x: x[0])
    return cmds


def schedule_commands(env: simpy.Environment, sender: Sender, server_sender: ServerSender, commands):
    for t_ms, typ, val in commands:
        if t_ms < env.now:
            t_ms = env.now
        yield env.timeout(t_ms - env.now)
        if typ == "control":
            sender.add_control(val)
        else:
            server_sender.set_download_allowed(val == 1)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Dropbox-like sync simulation using SimPy")
    p.add_argument(
        "--simulation_time",
        type=float,
        default=10_000_000.0,
        help="Simulation duration in milliseconds (simulation time). Default: 10000000.0",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    args = build_arg_parser().parse_args(argv)

    sim_time = float(args.simulation_time)
    if sim_time < 0:
        raise SystemExit("--simulation_time must be >= 0")

    # Read stdin up-front (fast; avoids any real-time behavior)
    commands = read_stdin_commands()

    env = simpy.Environment()
    logger = EventLogger(env)

    # Subnets (fixed 3s delay)
    subnet_a1 = DelayChannel(env, delay_ms=3_000.0)  # Sender -> ServerReceiver
    subnet_a2 = DelayChannel(env, delay_ms=3_000.0)  # ServerReceiver -> Sender
    subnet_b1 = DelayChannel(env, delay_ms=3_000.0)  # ServerSender -> Receiver
    subnet_b2 = DelayChannel(env, delay_ms=3_000.0)  # Receiver -> ServerSender

    storage_queue: simpy.Store = simpy.Store(env)

    sender = Sender(env, logger, data_out=subnet_a1.inbox, ack_in=subnet_a2.outbox)
    server_sender = ServerSender(env, logger, storage_queue, data_out=subnet_b1.inbox, ack_in=subnet_b2.outbox)
    server_receiver = ServerReceiver(
        env,
        logger,
        data_in=subnet_a1.outbox,
        ack_out=subnet_a2.inbox,
        storage_queue=storage_queue,
        on_storage_put=server_sender.notify,
    )
    receiver = Receiver(env, logger, data_in=subnet_b1.outbox, ack_out=subnet_b2.inbox)
    _ = (server_receiver, receiver)

    env.process(schedule_commands(env, sender, server_sender, commands))

    # SimPy requires 'until' to be > current time. Treat 0 as "do nothing".
    if sim_time > 0:
        env.run(until=sim_time)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
