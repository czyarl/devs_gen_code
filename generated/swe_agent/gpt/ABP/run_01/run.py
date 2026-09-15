#!/usr/bin/env python3
"""Alternating Bit Protocol (ABP) simulation using SimPy.

Implements the scenario described in the PR requirements.

Stdout: JSONL KPI stream only.
Stderr: optional diagnostics.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from typing import Any, Dict, Optional

import simpy


def _time(t: float) -> float:
    """Format simulation time as float with at least 2 decimals."""
    return float(round(float(t), 2))


class JsonlEmitter:
    def __init__(self, stream=sys.stdout):
        self.stream = stream

    def emit(self, *, time: float, entity: str, event: str, payload: Dict[str, Any]) -> None:
        rec = {"time": _time(time), "entity": entity, "event": event, "payload": payload}
        self.stream.write(json.dumps(rec, separators=(",", ":")) + "\n")
        self.stream.flush()


@dataclass(frozen=True)
class DataPacket:
    seq_num: int
    bit: int


@dataclass(frozen=True)
class AckPacket:
    bit: int


class Subnet:
    """Deterministic-loss channel with fixed transmission delay."""

    def __init__(
        self,
        env: simpy.Environment,
        emitter: JsonlEmitter,
        *,
        channel: str,  # "forward" or "backward"
        seed: int,
        channel_delay: float,
    ):
        self.env = env
        self.emitter = emitter
        self.channel = channel
        self.channel_delay = float(channel_delay)
        self._x = int(seed)

        self.in_store: simpy.Store = simpy.Store(env)
        self.out_store: simpy.Store = simpy.Store(env)

        env.process(self._run())

    def _decide(self) -> tuple[str, int]:
        x_new = (17 * self._x + 11) % 100
        self._x = x_new
        behavior = "drop" if x_new < 10 else "pass"
        return behavior, x_new

    def _run(self):
        while True:
            pkt = yield self.in_store.get()
            behavior, noise_value = self._decide()
            self.emitter.emit(
                time=self.env.now,
                entity="subnet",
                event="packet_get",
                payload={
                    "behavior": behavior,
                    "channel": self.channel,
                    "noise_value": int(noise_value),
                },
            )
            if behavior == "pass":
                yield self.env.timeout(self.channel_delay)
                yield self.out_store.put(pkt)


class Receiver:
    """Receiver with processing delay and buffer capacity 1 while busy.

    Important: packets that arrive while the receiver is busy are *immediately*
    either buffered (first arrival) or dropped (subsequent arrivals), i.e. they
    must not accumulate in an input queue.
    """

    def __init__(
        self,
        env: simpy.Environment,
        emitter: JsonlEmitter,
        *,
        receiver_delay: float,
        in_store: simpy.Store,
        ack_out_store: simpy.Store,
    ):
        self.env = env
        self.emitter = emitter
        self.receiver_delay = float(receiver_delay)
        self.in_store = in_store
        self.ack_out_store = ack_out_store

        self._buffer: Optional[DataPacket] = None

        env.process(self._run())

    def _handle_completed(self, pkt: DataPacket):
        self.emitter.emit(
            time=self.env.now,
            entity="receiver",
            event="packet_received",
            payload={"seq_num": int(pkt.seq_num), "bit": int(pkt.bit)},
        )
        yield self.ack_out_store.put(AckPacket(bit=int(pkt.bit)))

    def _run(self):
        # Single process to ensure we don't accidentally queue multiple packets
        # during the busy period.
        while True:
            # If we buffered something while busy, process it next.
            if self._buffer is not None:
                pkt = self._buffer
                self._buffer = None
            else:
                pkt = yield self.in_store.get()

            if not isinstance(pkt, DataPacket):
                continue

            # Start processing delay.
            self.emitter.emit(
                time=self.env.now,
                entity="receiver",
                event="delay_start",
                payload={"type": "processing", "duration": float(self.receiver_delay)},
            )
            done_ev = self.env.timeout(self.receiver_delay)

            # While busy, accept at most 1 additional packet into buffer; drop the rest.
            while True:
                arrival_ev = self.in_store.get()
                res = yield done_ev | arrival_ev

                # Handle arrival if it happened at/before completion time.
                if arrival_ev in res:
                    arrived = res[arrival_ev]
                    if isinstance(arrived, DataPacket) and self._buffer is None:
                        self._buffer = arrived

                if done_ev in res:
                    # If processing finished before the next arrival, cancel the pending get.
                    if arrival_ev not in res:
                        arrival_ev.cancel()
                    break

            # Processing completes now.
            yield from self._handle_completed(pkt)


class Sender:
    """Stop-and-wait ABP sender with preparation delay and timeout."""

    def __init__(
        self,
        env: simpy.Environment,
        emitter: JsonlEmitter,
        *,
        total_packets: int,
        timeout: float,
        sender_delay: float,
        data_out_store: simpy.Store,
        ack_in_store: simpy.Store,
    ):
        self.env = env
        self.emitter = emitter
        self.total_packets = int(total_packets)
        self.timeout = float(timeout)
        self.sender_delay = float(sender_delay)
        self.data_out_store = data_out_store
        self.ack_in_store = ack_in_store

        env.process(self._run())

    def _prep_and_send(self, pkt: DataPacket, *, is_retry: bool):
        self.emitter.emit(
            time=self.env.now,
            entity="sender",
            event="delay_start",
            payload={"type": "preparation", "duration": float(self.sender_delay)},
        )
        yield self.env.timeout(self.sender_delay)
        self.emitter.emit(
            time=self.env.now,
            entity="sender",
            event="packet_sent",
            payload={"seq_num": int(pkt.seq_num), "bit": int(pkt.bit), "is_retry": bool(is_retry)},
        )
        yield self.data_out_store.put(pkt)

    def _wait_for_valid_ack(self, expected_bit: int) -> bool:
        start = self.env.now
        remaining = self.timeout

        while True:
            if remaining <= 0:
                return False

            ack_get = self.ack_in_store.get()
            timeout_ev = self.env.timeout(remaining)
            res = yield self.env.any_of({ack_get, timeout_ev})

            if timeout_ev in res:
                return False

            ack = res[ack_get]
            if not isinstance(ack, AckPacket):
                elapsed = self.env.now - start
                remaining = self.timeout - elapsed
                continue

            is_valid = int(ack.bit) == int(expected_bit)
            self.emitter.emit(
                time=self.env.now,
                entity="sender",
                event="ack_received",
                payload={"ack_bit": int(ack.bit), "is_valid": bool(is_valid)},
            )
            if is_valid:
                return True

            elapsed = self.env.now - start
            remaining = self.timeout - elapsed

    def _run(self):
        bit = 0
        for seq in range(1, self.total_packets + 1):
            pkt = DataPacket(seq_num=seq, bit=bit)
            is_retry = False
            while True:
                yield from self._prep_and_send(pkt, is_retry=is_retry)
                ok = yield from self._wait_for_valid_ack(expected_bit=bit)
                if ok:
                    break
                is_retry = True
            bit = 1 - bit


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="ABP simulation (SimPy)")
    p.add_argument("--total_packets", type=int, required=True)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--timeout", type=int, default=20)
    p.add_argument("--sender_delay", type=int, default=10)
    p.add_argument("--receiver_delay", type=int, default=10)
    p.add_argument("--channel_delay", type=int, default=3)
    p.add_argument("--simulate_time", type=int, default=1000)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    env = simpy.Environment()
    emitter = JsonlEmitter(stream=sys.stdout)

    subnet_forward = Subnet(
        env,
        emitter,
        channel="forward",
        seed=args.seed,
        channel_delay=float(args.channel_delay),
    )
    subnet_backward = Subnet(
        env,
        emitter,
        channel="backward",
        seed=args.seed,
        channel_delay=float(args.channel_delay),
    )

    Receiver(
        env,
        emitter,
        receiver_delay=float(args.receiver_delay),
        in_store=subnet_forward.out_store,
        ack_out_store=subnet_backward.in_store,
    )

    Sender(
        env,
        emitter,
        total_packets=args.total_packets,
        timeout=float(args.timeout),
        sender_delay=float(args.sender_delay),
        data_out_store=subnet_forward.in_store,
        ack_in_store=subnet_backward.out_store,
    )

    env.run(until=float(args.simulate_time))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
