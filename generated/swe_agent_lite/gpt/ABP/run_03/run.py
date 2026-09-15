#!/usr/bin/env python3
"""Reliable Data Transfer with Deterministic Noise Interference (ABP).

This script simulates a Sender, Receiver, and two uni-directional channels
using Discrete Event Simulation (SimPy).

Stdout: JSONL KPI events only.
Stderr: any diagnostics (kept minimal).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from typing import Any, Dict, Optional

import simpy


def kpi_print(env: simpy.Environment, entity: str, event: str, payload: Dict[str, Any]) -> None:
    """Print a single KPI record to stdout as JSONL."""
    rec = {
        "time": float(f"{env.now:.2f}"),
        "entity": entity,
        "event": event,
        "payload": payload,
    }
    sys.stdout.write(json.dumps(rec) + "\n")


@dataclass(frozen=True)
class Packet:
    seq_num: int
    bit: int  # 0 or 1


@dataclass(frozen=True)
class Ack:
    bit: int  # 0 or 1


class Subnet:
    """A uni-directional channel with deterministic drop/pass behavior."""

    def __init__(
        self,
        env: simpy.Environment,
        channel: str,  # "forward" or "backward"
        seed: int,
        channel_delay: float,
        out_store: simpy.Store,
    ) -> None:
        self.env = env
        self.channel = channel
        self.x = int(seed)
        self.delay = float(channel_delay)
        self.out_store = out_store
        self.in_store: simpy.Store = simpy.Store(env)
        self.proc = env.process(self._run())

    def put(self, item: Any) -> None:
        self.in_store.put(item)

    def _next_noise(self) -> int:
        return (17 * self.x + 11) % 100

    def _run(self):
        while True:
            item = yield self.in_store.get()

            x_new = self._next_noise()
            behavior = "drop" if x_new < 10 else "pass"
            kpi_print(
                self.env,
                "subnet",
                "packet_get",
                {"behavior": behavior, "channel": self.channel, "noise_value": int(x_new)},
            )
            self.x = x_new

            if behavior == "drop":
                continue

            yield self.env.timeout(self.delay)
            yield self.out_store.put(item)


class Receiver:
    """Receiver with processing delay and capacity-1 buffer while busy."""

    def __init__(
        self,
        env: simpy.Environment,
        receiver_delay: float,
        in_store: simpy.Store,
        ack_subnet: Subnet,
    ) -> None:
        self.env = env
        self.delay = float(receiver_delay)
        self.in_store = in_store
        self.ack_subnet = ack_subnet

        self.busy = False
        self.buffer: Optional[Packet] = None

        self.proc = env.process(self._run())

    def _run(self):
        while True:
            pkt = yield self.in_store.get()

            if not self.busy:
                self.busy = True
                self.env.process(self._process(pkt))
            else:
                # capacity 1 buffer: store only first while busy
                if self.buffer is None:
                    self.buffer = pkt

    def _process(self, pkt: Packet):
        kpi_print(
            self.env,
            "receiver",
            "delay_start",
            {"type": "processing", "duration": float(f"{self.delay:.2f}")},
        )
        yield self.env.timeout(self.delay)

        kpi_print(
            self.env,
            "receiver",
            "packet_received",
            {"seq_num": int(pkt.seq_num), "bit": int(pkt.bit)},
        )

        # Immediately send ACK with same bit
        self.ack_subnet.put(Ack(bit=pkt.bit))

        # If something buffered, process it next immediately
        if self.buffer is not None:
            next_pkt = self.buffer
            self.buffer = None
            self.env.process(self._process(next_pkt))
        else:
            self.busy = False


class Sender:
    """Sender implementing Alternating Bit Protocol with timeout and retries."""

    def __init__(
        self,
        env: simpy.Environment,
        total_packets: int,
        sender_delay: float,
        timeout: float,
        data_subnet: Subnet,
        ack_in_store: simpy.Store,
    ) -> None:
        self.env = env
        self.total_packets = int(total_packets)
        self.sender_delay = float(sender_delay)
        self.timeout = float(timeout)
        self.data_subnet = data_subnet
        self.ack_in_store = ack_in_store

        self.proc = env.process(self._run())

    def _run(self):
        bit = 0
        for seq in range(1, self.total_packets + 1):
            pkt = Packet(seq_num=seq, bit=bit)
            yield from self._send_with_retries(pkt)
            bit = 1 - bit

    def _send_with_retries(self, pkt: Packet):
        is_retry = False
        while True:
            # preparation delay
            kpi_print(
                self.env,
                "sender",
                "delay_start",
                {"type": "preparation", "duration": float(f"{self.sender_delay:.2f}")},
            )
            yield self.env.timeout(self.sender_delay)

            # send packet into forward subnet
            kpi_print(
                self.env,
                "sender",
                "packet_sent",
                {"seq_num": int(pkt.seq_num), "bit": int(pkt.bit), "is_retry": bool(is_retry)},
            )
            self.data_subnet.put(pkt)

            # wait for ack or timeout
            ack_ev = self.env.process(self._wait_for_ack())
            timeout_ev = self.env.timeout(self.timeout)
            res = yield ack_ev | timeout_ev

            if timeout_ev in res:
                # timeout -> retransmit
                is_retry = True
                continue

            ack: Ack = res[ack_ev]
            is_valid = int(ack.bit) == int(pkt.bit)
            kpi_print(
                self.env,
                "sender",
                "ack_received",
                {"ack_bit": int(ack.bit), "is_valid": bool(is_valid)},
            )
            if is_valid:
                return
            # invalid ack -> keep waiting by retransmitting on next loop
            is_retry = True

    def _wait_for_ack(self):
        ack = yield self.ack_in_store.get()
        return ack


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="ABP simulation with deterministic channel loss")
    p.add_argument("--total_packets", type=int, required=True)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--timeout", type=int, default=20)
    p.add_argument("--sender_delay", type=int, default=10)
    p.add_argument("--receiver_delay", type=int, default=10)
    p.add_argument("--channel_delay", type=int, default=3)
    p.add_argument("--simulate_time", type=int, default=1000)
    return p


def main(argv=None) -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    args = build_arg_parser().parse_args(argv)

    env = simpy.Environment()

    # Stores between components
    receiver_in = simpy.Store(env)
    sender_ack_in = simpy.Store(env)

    # Subnets
    subnet_forward = Subnet(
        env=env,
        channel="forward",
        seed=args.seed,
        channel_delay=args.channel_delay,
        out_store=receiver_in,
    )
    subnet_backward = Subnet(
        env=env,
        channel="backward",
        seed=args.seed,
        channel_delay=args.channel_delay,
        out_store=sender_ack_in,
    )

    # Entities
    Receiver(env=env, receiver_delay=args.receiver_delay, in_store=receiver_in, ack_subnet=subnet_backward)
    Sender(
        env=env,
        total_packets=args.total_packets,
        sender_delay=args.sender_delay,
        timeout=args.timeout,
        data_subnet=subnet_forward,
        ack_in_store=sender_ack_in,
    )

    env.run(until=float(args.simulate_time))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
