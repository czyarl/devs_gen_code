#!/usr/bin/env python3
"""ABP_04 - Alternating Bit Protocol simulation using SimPy.

Entry point: run.py

Outputs:
- stdout: JSONL KPI/event records only
- stderr: any diagnostics

Implements: reliable data transfer with deterministic noise interference.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from typing import Any, Dict, Optional

import simpy


def _setup_stderr_logger() -> logging.Logger:
    logger = logging.getLogger("abp")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def emit_event(time_ms: float, entity: str, event: str, payload: Dict[str, Any]) -> None:
    rec = {
        "time": float(time_ms),
        "entity": str(entity),
        "event": str(event),
        "payload": payload or {},
    }
    # stdout must contain ONLY the JSONL event records
    sys.stdout.write(json.dumps(rec) + "\n")
    sys.stdout.flush()


@dataclass(frozen=True)
class DataPacket:
    seq_num: int
    bit: int  # 0/1


@dataclass(frozen=True)
class AckPacket:
    ack_bit: int  # 0/1


class Subnet:
    """Uni-directional channel with deterministic interference and fixed delay."""

    def __init__(
        self,
        env: simpy.Environment,
        channel: str,  # "forward" or "backward"
        seed: int,
        channel_delay: float,
        in_store: simpy.Store,
        out_store: simpy.Store,
    ) -> None:
        self.env = env
        self.channel = channel
        self.channel_delay = float(channel_delay)
        self.in_store = in_store
        self.out_store = out_store
        self.x = int(seed)
        env.process(self.run())

    def _advance_noise(self) -> int:
        # x_new = (17 * x_old + 11) mod 100
        return (17 * self.x + 11) % 100

    def run(self):
        while True:
            pkt = yield self.in_store.get()
            x_new = self._advance_noise()
            self.x = x_new

            behavior = "drop" if x_new < 10 else "pass"
            emit_event(
                self.env.now,
                "subnet",
                "packet_get",
                {"behavior": behavior, "channel": self.channel, "noise_value": int(x_new)},
            )

            if behavior == "drop":
                continue

            yield self.env.timeout(self.channel_delay)
            yield self.out_store.put(pkt)


class Receiver:
    """Receiver with processing delay and buffer capacity 1."""

    def __init__(
        self,
        env: simpy.Environment,
        receiver_delay: float,
        in_store: simpy.Store,
        ack_out_store: simpy.Store,
    ) -> None:
        self.env = env
        self.receiver_delay = float(receiver_delay)
        self.in_store = in_store
        self.ack_out_store = ack_out_store

        self.busy = False
        self.buffered: Optional[DataPacket] = None
        env.process(self.run())

    def _process_one(self, pkt: DataPacket):
        self.busy = True
        emit_event(
            self.env.now,
            "receiver",
            "delay_start",
            {"type": "processing", "duration": float(self.receiver_delay)},
        )
        yield self.env.timeout(self.receiver_delay)
        emit_event(
            self.env.now,
            "receiver",
            "packet_received",
            {"seq_num": int(pkt.seq_num), "bit": int(pkt.bit)},
        )
        yield self.ack_out_store.put(AckPacket(ack_bit=int(pkt.bit)))
        self.busy = False

        # process buffered packet immediately after becoming idle
        if self.buffered is not None:
            nxt = self.buffered
            self.buffered = None
            yield from self._process_one(nxt)

    def run(self):
        while True:
            pkt: DataPacket = yield self.in_store.get()
            if not self.busy:
                yield from self._process_one(pkt)
            else:
                # buffer capacity 1: keep only first arrival while busy
                if self.buffered is None:
                    self.buffered = pkt


class Sender:
    """Stop-and-wait sender with per-attempt preparation delay and timeout."""

    def __init__(
        self,
        env: simpy.Environment,
        total_packets: int,
        sender_delay: float,
        timeout: float,
        out_store: simpy.Store,
        ack_in_store: simpy.Store,
    ) -> None:
        self.env = env
        self.total_packets = int(total_packets)
        self.sender_delay = float(sender_delay)
        self.timeout = float(timeout)
        self.out_store = out_store
        self.ack_in_store = ack_in_store
        env.process(self.run())

    def run(self):
        for seq_num in range(1, self.total_packets + 1):
            bit = (seq_num - 1) % 2  # first bit 0
            is_retry = False

            while True:
                emit_event(
                    self.env.now,
                    "sender",
                    "delay_start",
                    {"type": "preparation", "duration": float(self.sender_delay)},
                )
                yield self.env.timeout(self.sender_delay)

                emit_event(
                    self.env.now,
                    "sender",
                    "packet_sent",
                    {"seq_num": int(seq_num), "bit": int(bit), "is_retry": bool(is_retry)},
                )
                yield self.out_store.put(DataPacket(seq_num=int(seq_num), bit=int(bit)))

                deadline = self.env.now + self.timeout

                # wait for a valid ack until deadline; ignore invalid acks
                while True:
                    remaining = deadline - self.env.now
                    if remaining <= 0:
                        is_retry = True
                        break

                    get_ev = self.ack_in_store.get()
                    t_ev = self.env.timeout(remaining)
                    result = yield simpy.events.AnyOf(self.env, [get_ev, t_ev])

                    if t_ev in result:
                        if not get_ev.triggered:
                            get_ev.cancel()
                        is_retry = True
                        break

                    ack: AckPacket = result[get_ev]
                    is_valid = int(ack.ack_bit) == int(bit)
                    emit_event(
                        self.env.now,
                        "sender",
                        "ack_received",
                        {"ack_bit": int(ack.ack_bit), "is_valid": bool(is_valid)},
                    )

                    if is_valid:
                        is_retry = False
                        break

                if not is_retry:
                    break


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Reliable data transfer ABP simulation")
    p.add_argument("--total_packets", type=int, required=True)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--timeout", type=int, default=20)
    p.add_argument("--sender_delay", type=int, default=10)
    p.add_argument("--receiver_delay", type=int, default=10)
    p.add_argument("--channel_delay", type=int, default=3)
    p.add_argument("--simulate_time", type=int, default=1000)
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    logger = _setup_stderr_logger()
    args = parse_args(argv)

    if args.total_packets < 0:
        logger.error("--total_packets must be >= 0")
        return 2

    env = simpy.Environment()

    # Connections between blocks
    s_to_subnet1 = simpy.Store(env)
    subnet1_to_r = simpy.Store(env)

    r_to_subnet2 = simpy.Store(env)
    subnet2_to_s = simpy.Store(env)

    # Subnets
    Subnet(
        env,
        channel="forward",
        seed=args.seed,
        channel_delay=float(args.channel_delay),
        in_store=s_to_subnet1,
        out_store=subnet1_to_r,
    )
    Subnet(
        env,
        channel="backward",
        seed=args.seed,
        channel_delay=float(args.channel_delay),
        in_store=r_to_subnet2,
        out_store=subnet2_to_s,
    )

    Receiver(
        env,
        receiver_delay=float(args.receiver_delay),
        in_store=subnet1_to_r,
        ack_out_store=r_to_subnet2,
    )
    Sender(
        env,
        total_packets=int(args.total_packets),
        sender_delay=float(args.sender_delay),
        timeout=float(args.timeout),
        out_store=s_to_subnet1,
        ack_in_store=subnet2_to_s,
    )

    env.run(until=float(args.simulate_time))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
