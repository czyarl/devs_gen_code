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

def parse_time_to_ms(token: str) -> float:
    """Parse HH:MM:SS or HH:MM:SS:mmm into milliseconds."""
    parts = token.strip().split(":")
    if len(parts) not in (3, 4):
        raise ValueError(f"Invalid time token: {token}")
    hh = int(parts[0])
    mm = int(parts[1])
    ss = int(parts[2])
    mmm = int(parts[3]) if len(parts) == 4 else 0
    return float((((hh * 60 + mm) * 60 + ss) * 1000) + mmm)


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


@dataclass(frozen=True)
class Packet:
    seq: int
    bit: int  # 0/1


@dataclass(frozen=True)
class Ack:
    bit: int  # 0/1


# ------------------------- network -------------------------

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

    def start(self, src: simpy.Store, dst: simpy.Store):
        def _run():
            while True:
                item = yield src.get()
                yield self.env.timeout(self.delay_ms)
                yield dst.put(item)
        self.env.process(_run())


# ------------------------- models -------------------------

class Sender:
    PREP_MS = 10_000.0
    TIMEOUT_MS = 20_000.0

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

        env.process(self._run())

    def control(self, n: int):
        if n <= 0:
            return
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

            # preparation before starting (or resuming after idle)
            self.log.emit("sender", "preparation_started", {"duration": int(self.PREP_MS)})
            yield self.env.timeout(self.PREP_MS)

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

                    ack_ev = self.in_ack.get()
                    to_ev = self.env.timeout(self.TIMEOUT_MS)
                    res = yield ack_ev | to_ev
                    if to_ev in res:
                        self.log.emit("sender", "timeout", {"seq": int(pkt.seq)})
                        is_retry = True
                        continue

                    ack = res[ack_ev]
                    if isinstance(ack, Ack) and ack.bit == pkt.bit:
                        self.log.emit("sender", "ack_received", {"bit": int(ack.bit)})
                        # success
                        self.total_remaining -= 1
                        self.seq += 1
                        self.bit ^= 1
                        break
                    else:
                        # ignore unexpected ack; keep waiting with timeout by retrying
                        is_retry = True
                        continue


class ServerReceiver:
    PROC_MS = 3_000.0

    def __init__(
        self,
        env: simpy.Environment,
        log: EventLogger,
        in_data: simpy.Store,
        out_ack: simpy.Store,
        storage_q: simpy.Store,
    ):
        self.env = env
        self.log = log
        self.in_data = in_data
        self.out_ack = out_ack
        self.storage_q = storage_q

        self.expected_bit = 0
        self.last_ack_bit = 1  # previous bit (for duplicates); init opposite of expected

        env.process(self._run())

    def _run(self):
        while True:
            pkt = yield self.in_data.get()
            if not isinstance(pkt, Packet):
                continue
            self.log.emit("server_receiver", "packet_received", {"seq": int(pkt.seq), "bit": int(pkt.bit)})
            yield self.env.timeout(self.PROC_MS)

            if pkt.bit == self.expected_bit:
                # accept
                ack_bit = pkt.bit
                yield self.out_ack.put(Ack(bit=ack_bit))
                self.log.emit("server_receiver", "ack_sent_to_sender", {"bit": int(ack_bit)})
                yield self.storage_q.put(pkt)
                self.last_ack_bit = ack_bit
                self.expected_bit ^= 1
            else:
                # duplicate
                ack_bit = self.last_ack_bit
                yield self.out_ack.put(Ack(bit=ack_bit))
                self.log.emit("server_receiver", "ack_sent_to_sender", {"bit": int(ack_bit)})


class ServerSender:
    def __init__(
        self,
        env: simpy.Environment,
        log: EventLogger,
        storage_q: simpy.Store,
        out_data: simpy.Store,
        in_ack: simpy.Store,
    ):
        self.env = env
        self.log = log
        self.storage_q = storage_q
        self.out_data = out_data
        self.in_ack = in_ack

        self.download_allowed = False
        self._valve_changed = simpy.Event(env)

        self.expected_ack_bit = 0
        self.waiting_for_ack = False

        env.process(self._run())

    def set_download_allowed(self, allowed: bool):
        allowed = bool(allowed)
        if allowed == self.download_allowed:
            # still emit change? spec says log when request input toggles; keep idempotent
            self.log.emit("server_sender", "download_valve_change", {"allowed": bool(self.download_allowed)})
            return
        self.download_allowed = allowed
        self.log.emit("server_sender", "download_valve_change", {"allowed": bool(self.download_allowed)})
        if not self._valve_changed.triggered:
            self._valve_changed.succeed()

    def _reset_valve_event(self):
        self._valve_changed = simpy.Event(self.env)

    def _run(self):
        while True:
            # wait until allowed and storage non-empty
            while not self.download_allowed or len(self.storage_q.items) == 0:
                self._reset_valve_event()
                # also wake when storage gets an item
                storage_get = self.storage_q.get() if False else None  # placeholder
                # We can't wait on Store.put directly; poll with small event by waiting on either valve change or next item arrival.
                # Implement by waiting on either valve change or an item arrival via a separate event.
                item_arrival = simpy.Event(self.env)

                def _watch_storage():
                    while True:
                        if len(self.storage_q.items) > 0:
                            if not item_arrival.triggered:
                                item_arrival.succeed()
                            return
                        yield self.env.timeout(1.0)

                self.env.process(_watch_storage())
                yield self._valve_changed | item_arrival

            # allowed and have data
            pkt = yield self.storage_q.get()
            if not isinstance(pkt, Packet):
                continue

            self.waiting_for_ack = True
            self.log.emit("server_sender", "packet_forwarded", {"seq": int(pkt.seq), "bit": int(pkt.bit)})
            yield self.out_data.put(pkt)

            # wait for correct ack
            while True:
                ack = yield self.in_ack.get()
                if isinstance(ack, Ack) and ack.bit == pkt.bit:
                    self.log.emit("server_sender", "ack_received_from_receiver", {"bit": int(ack.bit)})
                    break
                # ignore unexpected

            self.waiting_for_ack = False
            # graceful stop: if valve turned off during transfer, stop now (after finishing cycle)
            if not self.download_allowed:
                continue


class Receiver:
    PROC_MS = 10_000.0

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

        env.process(self._run())

    def _run(self):
        while True:
            pkt = yield self.in_data.get()
            if not isinstance(pkt, Packet):
                continue
            # receiver processes regardless; ABP receiver should ack duplicates too.
            self.log.emit("receiver", "processing_started", {"seq": int(pkt.seq), "duration": int(self.PROC_MS)})
            yield self.env.timeout(self.PROC_MS)

            if pkt.bit == self.expected_bit:
                ack_bit = pkt.bit
                self.expected_bit ^= 1
                self.last_ack_bit = ack_bit
            else:
                ack_bit = self.last_ack_bit

            yield self.out_ack.put(Ack(bit=ack_bit))
            self.log.emit("receiver", "ack_sent", {"bit": int(ack_bit)})


# ------------------------- input scheduling -------------------------

def read_commands_from_stdin() -> List[Tuple[float, str, int]]:
    cmds: List[Tuple[float, str, int]] = []
    for line in sys.stdin:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"Invalid input line: {line}")
        t_ms = parse_time_to_ms(parts[0])
        typ = parts[1]
        val = int(parts[2])
        if typ not in ("control", "request"):
            raise ValueError(f"Unknown command type: {typ}")
        cmds.append((t_ms, typ, val))
    cmds.sort(key=lambda x: x[0])
    return cmds


def schedule_commands(env: simpy.Environment, sender: Sender, server_sender: ServerSender, cmds):
    def _run():
        for t_ms, typ, val in cmds:
            if t_ms < env.now:
                continue
            yield env.timeout(t_ms - env.now)
            if typ == "control":
                sender.control(val)
            else:
                server_sender.set_download_allowed(bool(val))
    env.process(_run())


# ------------------------- main -------------------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--simulation_time",
        type=float,
        default=10_000_000.0,
        help="Simulation duration in milliseconds (default: 10000000.0)",
    )
    args = ap.parse_args(argv)

    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(message)s")

    env = simpy.Environment(initial_time=0.0)
    log = EventLogger(env)

    # stores between components (pre-link)
    s_to_a1 = simpy.Store(env)
    a1_to_srv = simpy.Store(env)

    srv_to_a2 = simpy.Store(env)
    a2_to_s = simpy.Store(env)

    srv_to_b1 = simpy.Store(env)
    b1_to_r = simpy.Store(env)

    r_to_b2 = simpy.Store(env)
    b2_to_srv = simpy.Store(env)

    # links (3s)
    Link(env, 3_000.0).start(s_to_a1, a1_to_srv)  # A1
    Link(env, 3_000.0).start(srv_to_a2, a2_to_s)  # A2
    Link(env, 3_000.0).start(srv_to_b1, b1_to_r)  # B1
    Link(env, 3_000.0).start(r_to_b2, b2_to_srv)  # B2

    storage_q = simpy.Store(env)

    sender = Sender(env, log, out_data=s_to_a1, in_ack=a2_to_s)
    server_receiver = ServerReceiver(env, log, in_data=a1_to_srv, out_ack=srv_to_a2, storage_q=storage_q)
    server_sender = ServerSender(env, log, storage_q=storage_q, out_data=srv_to_b1, in_ack=b2_to_srv)
    receiver = Receiver(env, log, in_data=b1_to_r, out_ack=r_to_b2)

    cmds = read_commands_from_stdin()
    schedule_commands(env, sender, server_sender, cmds)

    env.run(until=float(args.simulation_time))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
