#!/usr/bin/env python3
"""Dropbox-like sync simulation using two ABP loops (SimPy).

Stdout: JSONL event stream only.
Stderr: logs/debug.

Entry point: python run.py
"""

from __future__ import annotations

import argparse
import sys
import json
import logging
from dataclasses import dataclass
from collections import deque
import simpy


# ------------------------- utilities -------------------------

def parse_time_to_ms(token: str) -> float:
    """Parse HH:MM:SS or HH:MM:SS:mmm into milliseconds (float)."""
    parts = token.strip().split(":")
    if len(parts) not in (3, 4):
        raise ValueError(f"Invalid time token: {token}")
    hh = int(parts[0])
    mm = int(parts[1])
    ss = int(parts[2])
    ms = int(parts[3]) if len(parts) == 4 else 0
    return ((hh * 60 + mm) * 60 + ss) * 1000.0 + ms


class EventLogger:
    def __init__(self, env: simpy.Environment):
        self.env = env

    def emit(self, model: str, typ: str, val: dict):
        obj = {
            "timestamp_ms": float(self.env.now),
            "model": model,
            "type": typ,
            "val": val,
        }
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


@dataclass(frozen=True)
class Packet:
    seq: int
    bit: int  # 0/1


# ------------------------- network -------------------------

class DelayLink:
    """Reliable FIFO link with fixed delay."""

    def __init__(self, env: simpy.Environment, delay_ms: float):
        self.env = env
        self.delay_ms = delay_ms
        self._store = simpy.Store(env)

    def put(self, item):
        # preserve FIFO by enqueueing a delivery process per item
        def _deliver():
            yield self.env.timeout(self.delay_ms)
            yield self._store.put(item)

        self.env.process(_deliver())

    def get(self):
        return self._store.get()


# ------------------------- models -------------------------

class Sender:
    def __init__(
        self,
        env: simpy.Environment,
        log: EventLogger,
        data_out: DelayLink,
        ack_in: DelayLink,
    ):
        self.env = env
        self.log = log
        self.data_out = data_out
        self.ack_in = ack_in

        self.total_remaining = 0
        self._wake_evt = simpy.Event(env)

        self.seq = 1
        self.bit = 0

        self.env.process(self._run())

    def control(self, n: int):
        if n <= 0:
            return
        self.total_remaining += int(n)
        self.log.emit(
            "sender",
            "control_cmd",
            {"added": int(n), "total_remaining": int(self.total_remaining)},
        )
        if not self._wake_evt.triggered:
            self._wake_evt.succeed()

    def _reset_wake(self):
        self._wake_evt = simpy.Event(self.env)

    def _run(self):
        while True:
            if self.total_remaining <= 0:
                self._reset_wake()
                yield self._wake_evt
                continue

            # preparation before starting (or resuming) sending
            self.log.emit(
                "sender",
                "preparation_started",
                {"duration": 10000},
            )
            yield self.env.timeout(10000)

            while self.total_remaining > 0:
                # ABP send with timeout/retry
                pkt = Packet(seq=self.seq, bit=self.bit)
                is_retry = False
                while True:
                    self.data_out.put(pkt)
                    self.log.emit(
                        "sender",
                        "packet_sent",
                        {"seq": pkt.seq, "bit": pkt.bit, "is_retry": bool(is_retry)},
                    )

                    ack_ev = self.ack_in.get()
                    timeout_ev = self.env.timeout(20000)
                    res = yield ack_ev | timeout_ev

                    if timeout_ev in res:
                        self.log.emit("sender", "timeout", {"seq": pkt.seq})
                        is_retry = True
                        continue

                    ack_bit = int(res[ack_ev])
                    self.log.emit("sender", "ack_received", {"bit": ack_bit})
                    if ack_bit == pkt.bit:
                        # success
                        self.total_remaining -= 1
                        self.seq += 1
                        self.bit = 1 - self.bit
                        break
                    # wrong ack bit -> keep waiting by retransmitting on timeout; simplest: retry immediately
                    is_retry = True


class ServerReceiver:
    def __init__(
        self,
        env: simpy.Environment,
        log: EventLogger,
        data_in: DelayLink,
        ack_out: DelayLink,
        storage: deque[Packet],
    ):
        self.env = env
        self.log = log
        self.data_in = data_in
        self.ack_out = ack_out
        self.storage = storage

        self.expected_bit = 0
        self.last_acked_bit = 1  # previous bit (for duplicates)

        self.env.process(self._run())

    def _run(self):
        while True:
            pkt: Packet = yield self.data_in.get()
            self.log.emit(
                "server_receiver",
                "packet_received",
                {"seq": pkt.seq, "bit": pkt.bit},
            )
            yield self.env.timeout(3000)

            if pkt.bit == self.expected_bit:
                # accept
                self.ack_out.put(pkt.bit)
                self.log.emit(
                    "server_receiver",
                    "ack_sent_to_sender",
                    {"bit": pkt.bit},
                )
                self.storage.append(pkt)
                self.last_acked_bit = pkt.bit
                self.expected_bit = 1 - self.expected_bit
            else:
                # duplicate
                self.ack_out.put(self.last_acked_bit)
                self.log.emit(
                    "server_receiver",
                    "ack_sent_to_sender",
                    {"bit": self.last_acked_bit},
                )


class ServerSender:
    def __init__(
        self,
        env: simpy.Environment,
        log: EventLogger,
        data_out: DelayLink,
        ack_in: DelayLink,
        storage: deque[Packet],
    ):
        self.env = env
        self.log = log
        self.data_out = data_out
        self.ack_in = ack_in
        self.storage = storage

        self.download_allowed = False
        self._wake_evt = simpy.Event(env)

        self.waiting_for_ack = False
        self.expected_ack_bit = 0

        self.env.process(self._run())

    def set_download_allowed(self, allowed: bool):
        self.download_allowed = bool(allowed)
        self.log.emit(
            "server_sender",
            "download_valve_change",
            {"allowed": bool(self.download_allowed)},
        )
        if not self._wake_evt.triggered:
            self._wake_evt.succeed()

    def notify_storage_changed(self):
        if not self._wake_evt.triggered:
            self._wake_evt.succeed()

    def _reset_wake(self):
        self._wake_evt = simpy.Event(self.env)

    def _run(self):
        while True:
            # wait until conditions might be satisfied
            if (not self.download_allowed) or self.waiting_for_ack or (len(self.storage) == 0):
                self._reset_wake()
                yield self._wake_evt
                continue

            # pop and send one packet
            pkt = self.storage.popleft()
            self.waiting_for_ack = True
            self.expected_ack_bit = pkt.bit

            self.data_out.put(pkt)
            self.log.emit(
                "server_sender",
                "packet_forwarded",
                {"seq": pkt.seq, "bit": pkt.bit},
            )

            # wait for ack (no timeout specified)
            ack_bit = int((yield self.ack_in.get()))
            self.log.emit(
                "server_sender",
                "ack_received_from_receiver",
                {"bit": ack_bit},
            )
            # ABP: accept only matching bit; if mismatch, keep waiting (but receiver should be correct)
            if ack_bit == self.expected_ack_bit:
                self.waiting_for_ack = False
            else:
                # keep waiting until correct ack arrives
                while True:
                    ack_bit2 = int((yield self.ack_in.get()))
                    self.log.emit(
                        "server_sender",
                        "ack_received_from_receiver",
                        {"bit": ack_bit2},
                    )
                    if ack_bit2 == self.expected_ack_bit:
                        self.waiting_for_ack = False
                        break

            # if download_allowed turned off during transfer, loop will stop naturally next iteration


class Receiver:
    def __init__(
        self,
        env: simpy.Environment,
        log: EventLogger,
        data_in: DelayLink,
        ack_out: DelayLink,
    ):
        self.env = env
        self.log = log
        self.data_in = data_in
        self.ack_out = ack_out

        self.expected_bit = 0
        self.last_acked_bit = 1

        self.env.process(self._run())

    def _run(self):
        while True:
            pkt: Packet = yield self.data_in.get()
            # receiver processing starts immediately upon arrival
            self.log.emit(
                "receiver",
                "processing_started",
                {"seq": pkt.seq, "duration": 10000},
            )
            yield self.env.timeout(10000)

            if pkt.bit == self.expected_bit:
                self.ack_out.put(pkt.bit)
                self.log.emit("receiver", "ack_sent", {"bit": pkt.bit})
                self.last_acked_bit = pkt.bit
                self.expected_bit = 1 - self.expected_bit
            else:
                # duplicate
                self.ack_out.put(self.last_acked_bit)
                self.log.emit("receiver", "ack_sent", {"bit": self.last_acked_bit})


# ------------------------- orchestration -------------------------

@dataclass
class Command:
    t_ms: float
    typ: str
    val: int


def read_commands(stdin) -> list[Command]:
    cmds: list[Command] = []
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"Invalid command line: {line}")
        t_ms = parse_time_to_ms(parts[0])
        typ = parts[1]
        val = int(parts[2])
        if typ not in ("control", "request"):
            raise ValueError(f"Unknown command type: {typ}")
        cmds.append(Command(t_ms=t_ms, typ=typ, val=val))
    cmds.sort(key=lambda c: c.t_ms)
    return cmds


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--simulation_time",
        type=float,
        default=10000_000.0,
        help="Simulation duration in milliseconds (simulation time).",
    )
    args = ap.parse_args(argv)

    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

    env = simpy.Environment(initial_time=0.0)
    log = EventLogger(env)

    # links (3s each)
    A1 = DelayLink(env, 3000)
    A2 = DelayLink(env, 3000)
    B1 = DelayLink(env, 3000)
    B2 = DelayLink(env, 3000)

    storage: deque[Packet] = deque()

    sender = Sender(env, log, data_out=A1, ack_in=A2)
    server_receiver = ServerReceiver(env, log, data_in=A1, ack_out=A2, storage=storage)
    server_sender = ServerSender(env, log, data_out=B1, ack_in=B2, storage=storage)
    receiver = Receiver(env, log, data_in=B1, ack_out=B2)

    # notify server_sender when storage changes: easiest is to wrap append in server_receiver,
    # but we already append there; so add a small polling notifier process.
    def storage_notifier():
        last_len = 0
        while True:
            if len(storage) != last_len:
                last_len = len(storage)
                server_sender.notify_storage_changed()
            yield env.timeout(1)  # 1ms granularity, simulation time

    env.process(storage_notifier())

    cmds = read_commands(sys.stdin)

    def command_injector():
        for c in cmds:
            if c.t_ms < env.now:
                continue
            yield env.timeout(c.t_ms - env.now)
            if c.typ == "control":
                sender.control(c.val)
            else:
                server_sender.set_download_allowed(bool(c.val))
        # no more commands

    env.process(command_injector())

    env.run(until=float(args.simulation_time))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
