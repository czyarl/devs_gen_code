#!/usr/bin/env python3
"""Reliable Data Transfer Simulation (Alternating Bit Protocol) with deterministic loss.

Outputs JSONL KPI events to stdout only.
Any non-KPI logs go to stderr.

Implements a DES using simpy.
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
    logger = logging.getLogger("abp_sim")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    logger.handlers[:] = [handler]
    logger.propagate = False
    return logger


def emit(time: float, entity: str, event: str, payload: Dict[str, Any]) -> None:
    # Keep at least 2 decimals
    rec = {
        "time": float(f"{time:.2f}"),
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
    """Unidirectional channel with deterministic drop/pass decision."""

    def __init__(
        self,
        env: simpy.Environment,
        *,
        channel: str,  # "forward" or "backward"
        seed: int,
        channel_delay: float,
        out_store: simpy.Store,
    ) -> None:
        self.env = env
        self.channel = channel
        self.x = int(seed)
        self.delay = float(channel_delay)
        self.in_store: simpy.Store = simpy.Store(env)
        self.out_store = out_store
        self.proc = env.process(self._run())

    def _next_noise(self) -> int:
        return (17 * self.x + 11) % 100

    def _run(self):
        while True:
            item = yield self.in_store.get()
            x_new = self._next_noise()
            behavior = "drop" if x_new < 10 else "pass"
            emit(self.env.now, "subnet", "packet_get", {
                "behavior": behavior,
                "channel": self.channel,
                "noise_value": int(x_new),
            })
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
        *,
        receiver_delay: float,
        in_store: simpy.Store,
        ack_out_store: simpy.Store,
    ) -> None:
        self.env = env
        self.delay = float(receiver_delay)
        self.in_store = in_store
        self.ack_out_store = ack_out_store

        self._busy = False
        self._buffer: Optional[Packet] = None

        self.proc = env.process(self._run())

    def _run(self):
        while True:
            pkt: Packet = yield self.in_store.get()
            if not self._busy:
                self._busy = True
                self.env.process(self._process(pkt))
            else:
                # buffer capacity 1; keep only first while busy
                if self._buffer is None:
                    self._buffer = pkt

    def _process(self, pkt: Packet):
        emit(self.env.now, "receiver", "delay_start", {
            "type": "processing",
            "duration": float(self.delay),
        })
        yield self.env.timeout(self.delay)
        emit(self.env.now, "receiver", "packet_received", {
            "seq_num": int(pkt.seq_num),
            "bit": int(pkt.bit),
        })
        # Immediately send ACK with same bit
        yield self.ack_out_store.put(Ack(bit=pkt.bit))

        # After finishing, if buffered packet exists, process it immediately
        if self._buffer is not None:
            next_pkt = self._buffer
            self._buffer = None
            self.env.process(self._process(next_pkt))
        else:
            self._busy = False


class Sender:
    """Stop-and-wait ABP sender with preparation delay and timeout retransmissions."""

    def __init__(
        self,
        env: simpy.Environment,
        *,
        total_packets: int,
        sender_delay: float,
        timeout: float,
        data_out_store: simpy.Store,
        ack_in_store: simpy.Store,
    ) -> None:
        self.env = env
        self.total_packets = int(total_packets)
        self.sender_delay = float(sender_delay)
        self.timeout = float(timeout)
        self.data_out_store = data_out_store
        self.ack_in_store = ack_in_store

        self.proc = env.process(self._run())

    def _run(self):
        bit = 0
        for seq in range(1, self.total_packets + 1):
            pkt = Packet(seq_num=seq, bit=bit)
            is_retry = False
            while True:
                # preparation delay
                emit(self.env.now, "sender", "delay_start", {
                    "type": "preparation",
                    "duration": float(self.sender_delay),
                })
                yield self.env.timeout(self.sender_delay)

                emit(self.env.now, "sender", "packet_sent", {
                    "seq_num": int(pkt.seq_num),
                    "bit": int(pkt.bit),
                    "is_retry": bool(is_retry),
                })
                yield self.data_out_store.put(pkt)

                # wait for ack or timeout
                ack_event = self.ack_in_store.get()
                timeout_event = self.env.timeout(self.timeout)
                res = yield ack_event | timeout_event

                if timeout_event in res:
                    is_retry = True
                    continue

                ack: Ack = res[ack_event]
                is_valid = int(ack.bit) == int(pkt.bit)
                emit(self.env.now, "sender", "ack_received", {
                    "ack_bit": int(ack.bit),
                    "is_valid": bool(is_valid),
                })
                if is_valid:
                    bit = 1 - bit
                    break
                # invalid ack: keep waiting by retransmitting on next loop
                is_retry = True


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ABP reliable transfer simulation with deterministic loss")
    p.add_argument("--total_packets", type=int, required=True)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--timeout", type=int, default=20)
    p.add_argument("--sender_delay", type=int, default=10)
    p.add_argument("--receiver_delay", type=int, default=10)
    p.add_argument("--channel_delay", type=int, default=3)
    p.add_argument("--simulate_time", type=int, default=1000)
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    _setup_stderr_logger()
    args = parse_args(argv)

    env = simpy.Environment()

    # Stores between components
    sender_to_subnet = simpy.Store(env)
    subnet_to_receiver = simpy.Store(env)
    receiver_to_subnet = simpy.Store(env)
    subnet_to_sender = simpy.Store(env)

    # Channels
    forward = Subnet(env, channel="forward", seed=args.seed, channel_delay=args.channel_delay, out_store=subnet_to_receiver)
    backward = Subnet(env, channel="backward", seed=args.seed, channel_delay=args.channel_delay, out_store=subnet_to_sender)

    # Wire inputs
    forward.in_store = sender_to_subnet
    backward.in_store = receiver_to_subnet

    # Receiver and Sender
    Receiver(env, receiver_delay=args.receiver_delay, in_store=subnet_to_receiver, ack_out_store=receiver_to_subnet)
    Sender(
        env,
        total_packets=args.total_packets,
        sender_delay=args.sender_delay,
        timeout=args.timeout,
        data_out_store=sender_to_subnet,
        ack_in_store=subnet_to_sender,
    )

    env.run(until=float(args.simulate_time))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
