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
from typing import Any, Dict, Optional, List, Tuple

import simpy


# ------------------------- utilities -------------------------

def parse_time_to_ms(s: str) -> float:
    """Parse HH:MM:SS or HH:MM:SS:mmm into milliseconds."""
    parts = s.strip().split(":")
    if len(parts) not in (3, 4):
        raise ValueError(f"Invalid time format: {s}")
    hh = int(parts[0])
    mm = int(parts[1])
    ss = int(parts[2])
    ms = int(parts[3]) if len(parts) == 4 else 0
    return ((hh * 60 + mm) * 60 + ss) * 1000.0 + ms


class EventLogger:
    def __init__(self, env: simpy.Environment):
        self.env = env

    def emit(self, model: str, typ: str, val: Dict[str, Any]):
        obj = {
            "timestamp_ms": float(self.env.now),
            "model": model,
            "type": typ,
            "val": val,
        }
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


@dataclass
class Packet:
    seq: int
    bit: int  # 0/1


# ------------------------- network links -------------------------

class Link:
    """Reliable FIFO link with fixed delay."""

    def __init__(self, env: simpy.Environment, delay_ms: float):
        self.env = env
        self.delay_ms = delay_ms
        self._store = simpy.Store(env)

    def put(self, item: Any):
        return self._store.put(item)

    def get(self):
        return self._store.get()

    def start(self, src_store: simpy.Store, dst_store: simpy.Store):
        def _run():
            while True:
                msg = yield src_store.get()
                yield self.env.timeout(self.delay_ms)
                yield dst_store.put(msg)

        self.env.process(_run())


# ------------------------- models -------------------------

class Sender:
    def __init__(
        self,
        env: simpy.Environment,
        log: EventLogger,
        out_data: simpy.Store,
        in_ack: simpy.Store,
    ):
        self.env = env
        self.log = log
        self.out_data = out_data
        self.in_ack = in_ack

        self.total_remaining = 0
        self._wakeup = simpy.Event(env)

        self.seq = 1
        self.bit = 0

        self.env.process(self._run())

    def add_control(self, n: int):
        self.total_remaining += n
        self.log.emit("sender", "control_cmd", {"added": int(n), "total_remaining": int(self.total_remaining)})
        if not self._wakeup.triggered:
            self._wakeup.succeed()

    def _reset_wakeup(self):
        self._wakeup = simpy.Event(self.env)

    def _run(self):
        while True:
            if self.total_remaining <= 0:
                self._reset_wakeup()
                yield self._wakeup
                continue

            # preparation before starting (only when transitioning from idle)
            self.log.emit("sender", "preparation_started", {"duration": 10000})
            yield self.env.timeout(10000)

            while self.total_remaining > 0:
                pkt = Packet(seq=self.seq, bit=self.bit)
                is_retry = False
                while True:
                    self.log.emit(
                        "sender",
                        "packet_sent",
                        {"seq": int(pkt.seq), "bit": int(pkt.bit), "is_retry": bool(is_retry)},
                    )
                    yield self.out_data.put(pkt)

                    ack_ev = self.env.process(self._wait_for_ack(pkt.bit))
                    timeout_ev = self.env.timeout(20000)
                    res = yield ack_ev | timeout_ev
                    if timeout_ev in res:
                        self.log.emit("sender", "timeout", {"seq": int(pkt.seq)})
                        is_retry = True
                        continue
                    else:
                        # ack received
                        self.log.emit("sender", "ack_received", {"bit": int(pkt.bit)})
                        break

                # success
                self.total_remaining -= 1
                self.seq += 1
                self.bit ^= 1

            # loop back to idle; if more control arrives during sending, total_remaining will be >0 and we won't idle.

    def _wait_for_ack(self, expected_bit: int):
        while True:
            ack_bit = yield self.in_ack.get()
            if int(ack_bit) == int(expected_bit):
                return


class ServerReceiver:
    def __init__(
        self,
        env: simpy.Environment,
        log: EventLogger,
        in_data: simpy.Store,
        out_ack: simpy.Store,
        storage: simpy.Store,
    ):
        self.env = env
        self.log = log
        self.in_data = in_data
        self.out_ack = out_ack
        self.storage = storage

        self.expected_bit = 0
        self.last_ack_bit = 1  # previous bit (for duplicates); initial previous is 1 when expected is 0

        self.env.process(self._run())

    def _run(self):
        while True:
            pkt: Packet = yield self.in_data.get()
            self.log.emit("server_receiver", "packet_received", {"seq": int(pkt.seq), "bit": int(pkt.bit)})
            yield self.env.timeout(3000)

            if pkt.bit == self.expected_bit:
                # accept
                yield self.out_ack.put(pkt.bit)
                self.log.emit("server_receiver", "ack_sent_to_sender", {"bit": int(pkt.bit)})
                yield self.storage.put(pkt)
                self.last_ack_bit = pkt.bit
                self.expected_bit ^= 1
            else:
                # duplicate
                yield self.out_ack.put(self.last_ack_bit)
                self.log.emit("server_receiver", "ack_sent_to_sender", {"bit": int(self.last_ack_bit)})


class ServerSender:
    def __init__(
        self,
        env: simpy.Environment,
        log: EventLogger,
        storage: simpy.Store,
        out_data: simpy.Store,
        in_ack: simpy.Store,
    ):
        self.env = env
        self.log = log
        self.storage = storage
        self.out_data = out_data
        self.in_ack = in_ack

        self.download_allowed = False
        self._wakeup = simpy.Event(env)

        self.expected_ack_bit = 0
        self.waiting_for_ack = False

        self.env.process(self._run())

    def set_download_allowed(self, allowed: bool):
        self.download_allowed = bool(allowed)
        self.log.emit("server_sender", "download_valve_change", {"allowed": bool(self.download_allowed)})
        if not self._wakeup.triggered:
            self._wakeup.succeed()

    def notify_storage_changed(self):
        if not self._wakeup.triggered:
            self._wakeup.succeed()

    def _reset_wakeup(self):
        self._wakeup = simpy.Event(self.env)

    def _run(self):
        while True:
            # wait until conditions might be satisfied
            if (not self.download_allowed) or self.waiting_for_ack or (len(self.storage.items) == 0):
                self._reset_wakeup()
                yield self._wakeup
                continue

            # pop and send
            pkt: Packet = yield self.storage.get()
            self.waiting_for_ack = True
            self.log.emit("server_sender", "packet_forwarded", {"seq": int(pkt.seq), "bit": int(pkt.bit)})
            yield self.out_data.put(pkt)

            # wait for correct ack
            while True:
                ack_bit = yield self.in_ack.get()
                if int(ack_bit) == int(pkt.bit):
                    self.log.emit("server_sender", "ack_received_from_receiver", {"bit": int(ack_bit)})
                    break
            self.waiting_for_ack = False
            # graceful stop: if download_allowed turned off during transfer, loop will block next iteration.


class Receiver:
    def __init__(
        self,
        env: simpy.Environment,
        log: EventLogger,
        in_data: simpy.Store,
        out_ack: simpy.Store,
    ):
        self.env = env
        self.log = log
        self.in_data = in_data
        self.out_ack = out_ack

        self.expected_bit = 0
        self.last_ack_bit = 1

        self.env.process(self._run())

    def _run(self):
        while True:
            pkt: Packet = yield self.in_data.get()
            # ABP receiver: accept only expected bit; duplicates still ack last accepted
            if pkt.bit == self.expected_bit:
                self.log.emit("receiver", "processing_started", {"seq": int(pkt.seq), "duration": 10000})
                yield self.env.timeout(10000)
                yield self.out_ack.put(pkt.bit)
                self.log.emit("receiver", "ack_sent", {"bit": int(pkt.bit)})
                self.last_ack_bit = pkt.bit
                self.expected_bit ^= 1
            else:
                # duplicate: no processing delay specified; still ack previous
                yield self.out_ack.put(self.last_ack_bit)
                self.log.emit("receiver", "ack_sent", {"bit": int(self.last_ack_bit)})


# ------------------------- input scheduling -------------------------

def read_commands_from_stdin() -> List[Tuple[float, str, int]]:
    cmds: List[Tuple[float, str, int]] = []
    for line in sys.stdin:
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
        cmds.append((t_ms, typ, val))
    cmds.sort(key=lambda x: x[0])
    return cmds


def schedule_commands(
    env: simpy.Environment,
    cmds: List[Tuple[float, str, int]],
    sender: Sender,
    server_sender: ServerSender,
):
    def _run():
        for t_ms, typ, val in cmds:
            if t_ms < env.now:
                continue
            yield env.timeout(t_ms - env.now)
            if typ == "control":
                sender.add_control(val)
            else:
                server_sender.set_download_allowed(bool(val))

    env.process(_run())


# ------------------------- main -------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Dropbox-like sync simulation (two ABP loops)")
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=10000_000.0,
        help="Simulation duration in milliseconds (default: 10000000.0)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s:%(message)s")

    env = simpy.Environment(initial_time=0.0)
    log = EventLogger(env)

    # Stores between components (instantaneous endpoints)
    sender_to_a1 = simpy.Store(env)
    a1_to_srv = simpy.Store(env)

    srv_to_a2 = simpy.Store(env)
    a2_to_sender = simpy.Store(env)

    srv_to_b1 = simpy.Store(env)
    b1_to_rcv = simpy.Store(env)

    rcv_to_b2 = simpy.Store(env)
    b2_to_srv = simpy.Store(env)

    # Links (3s delay)
    Link(env, 3000).start(sender_to_a1, a1_to_srv)  # A1
    Link(env, 3000).start(srv_to_a2, a2_to_sender)  # A2
    Link(env, 3000).start(srv_to_b1, b1_to_rcv)  # B1
    Link(env, 3000).start(rcv_to_b2, b2_to_srv)  # B2

    storage = simpy.Store(env)

    sender = Sender(env, log, out_data=sender_to_a1, in_ack=a2_to_sender)
    server_receiver = ServerReceiver(env, log, in_data=a1_to_srv, out_ack=srv_to_a2, storage=storage)
    server_sender = ServerSender(env, log, storage=storage, out_data=srv_to_b1, in_ack=b2_to_srv)
    receiver = Receiver(env, log, in_data=b1_to_rcv, out_ack=rcv_to_b2)

    # Wake server_sender when storage gets new items
    def storage_watcher():
        last_len = 0
        while True:
            yield env.timeout(1)
            cur_len = len(storage.items)
            if cur_len != last_len:
                server_sender.notify_storage_changed()
                last_len = cur_len

    env.process(storage_watcher())

    cmds = read_commands_from_stdin()
    schedule_commands(env, cmds, sender, server_sender)

    # Run simulation
    env.run(until=float(args.simulation_time))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
