#!/usr/bin/env python3
"""Reliable Data Transfer with Deterministic Noise Interference (ABP)

This script simulates a Sender, Receiver, and two uni-directional channels
using Discrete Event Simulation (SimPy).

Stdout: JSONL KPI events only.
Stderr: any other logs (kept minimal).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
import simpy


def emit(time: float, entity: str, event: str, payload: dict) -> None:
    """Emit one KPI record to stdout as JSONL."""
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
    """Deterministic-loss channel with fixed delay."""

    def __init__(
        self,
        env: simpy.Environment,
        *,
        name: str,
        channel: str,  # "forward" or "backward"
        delay: float,
        seed: int,
        out_store: simpy.Store,
    ) -> None:
        self.env = env
        self.name = name
        self.channel = channel
        self.delay = float(delay)
        self.x = int(seed)
        self.out_store = out_store

    def _next_noise(self) -> int:
        self.x = (17 * self.x + 11) % 100
        return self.x

    def put(self, item) -> simpy.events.Event:
        """Called when a packet/ack arrives at the subnet."""
        noise = self._next_noise()
        behavior = "drop" if noise < 10 else "pass"
        emit(self.env.now, "subnet", "packet_get", {
            "behavior": behavior,
            "channel": self.channel,
            "noise_value": int(noise),
        })

        if behavior == "drop":
            # Vanishes immediately.
            return self.env.event().succeed(True)

        def _deliver():
            yield self.env.timeout(self.delay)
            yield self.out_store.put(item)

        return self.env.process(_deliver())


class Receiver:
    """Receiver with processing delay and capacity-1 buffer."""

    def __init__(
        self,
        env: simpy.Environment,
        *,
        in_store: simpy.Store,
        subnet_back: Subnet,
        receiver_delay: float,
    ) -> None:
        self.env = env
        self.in_store = in_store
        self.subnet_back = subnet_back
        self.receiver_delay = float(receiver_delay)

        self._busy = False
        self._buffer: Packet | None = None

        self.proc = env.process(self._run())

    def _start_processing(self, pkt: Packet):
        emit(self.env.now, "receiver", "delay_start", {
            "type": "processing",
            "duration": float(self.receiver_delay),
        })

        yield self.env.timeout(self.receiver_delay)
        emit(self.env.now, "receiver", "packet_received", {
            "seq_num": int(pkt.seq_num),
            "bit": int(pkt.bit),
        })
        # Immediately send ACK with same bit.
        ack = Ack(bit=pkt.bit)
        self.subnet_back.put(ack)

    def _run(self):
        while True:
            pkt = yield self.in_store.get()
            if not self._busy:
                self._busy = True
                yield from self._start_processing(pkt)
                # After finishing, if something buffered, process it next.
                while self._buffer is not None:
                    buffered = self._buffer
                    self._buffer = None
                    yield from self._start_processing(buffered)
                self._busy = False
            else:
                # Buffer capacity 1: keep only first during busy.
                if self._buffer is None:
                    self._buffer = pkt


class Sender:
    """Alternating Bit Protocol sender with preparation delay and timeout."""

    def __init__(
        self,
        env: simpy.Environment,
        *,
        total_packets: int,
        sender_delay: float,
        timeout: float,
        subnet_fwd: Subnet,
        ack_in: simpy.Store,
    ) -> None:
        self.env = env
        self.total_packets = int(total_packets)
        self.sender_delay = float(sender_delay)
        self.timeout = float(timeout)
        self.subnet_fwd = subnet_fwd
        self.ack_in = ack_in

        self.proc = env.process(self._run())

    def _run(self):
        bit = 0
        for seq in range(1, self.total_packets + 1):
            is_retry = False
            while True:
                emit(self.env.now, "sender", "delay_start", {
                    "type": "preparation",
                    "duration": float(self.sender_delay),
                })
                yield self.env.timeout(self.sender_delay)

                emit(self.env.now, "sender", "packet_sent", {
                    "seq_num": int(seq),
                    "bit": int(bit),
                    "is_retry": bool(is_retry),
                })
                self.subnet_fwd.put(Packet(seq_num=seq, bit=bit))

                # Wait for either ACK or timeout.
                ack_ev = self.env.process(self._wait_for_ack())
                to_ev = self.env.timeout(self.timeout)
                res = yield ack_ev | to_ev

                if to_ev in res:
                    # Timeout: retry.
                    is_retry = True
                    # Cancel ack wait process to avoid leaking.
                    ack_ev.interrupt("timeout")
                    continue

                ack: Ack = res[ack_ev]
                is_valid = int(ack.bit) == int(bit)
                emit(self.env.now, "sender", "ack_received", {
                    "ack_bit": int(ack.bit),
                    "is_valid": bool(is_valid),
                })
                if is_valid:
                    bit = 1 - bit
                    break
                # Invalid ACK: keep waiting by retransmitting on next loop.
                is_retry = True

    def _wait_for_ack(self):
        try:
            ack = yield self.ack_in.get()
            return ack
        except simpy.Interrupt:
            return None


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ABP simulation with deterministic noise")
    p.add_argument("--total_packets", type=int, required=True)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--timeout", type=int, default=20)
    p.add_argument("--sender_delay", type=int, default=10)
    p.add_argument("--receiver_delay", type=int, default=10)
    p.add_argument("--channel_delay", type=int, default=3)
    p.add_argument("--simulate_time", type=int, default=1000)
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    env = simpy.Environment()

    # Stores between components.
    recv_in = simpy.Store(env)
    sender_ack_in = simpy.Store(env)

    subnet1 = Subnet(
        env,
        name="subnet1",
        channel="forward",
        delay=float(args.channel_delay),
        seed=int(args.seed),
        out_store=recv_in,
    )
    subnet2 = Subnet(
        env,
        name="subnet2",
        channel="backward",
        delay=float(args.channel_delay),
        seed=int(args.seed),
        out_store=sender_ack_in,
    )

    Receiver(
        env,
        in_store=recv_in,
        subnet_back=subnet2,
        receiver_delay=float(args.receiver_delay),
    )

    Sender(
        env,
        total_packets=int(args.total_packets),
        sender_delay=float(args.sender_delay),
        timeout=float(args.timeout),
        subnet_fwd=subnet1,
        ack_in=sender_ack_in,
    )

    env.run(until=float(args.simulate_time))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
