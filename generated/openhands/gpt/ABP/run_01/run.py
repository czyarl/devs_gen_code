#!/usr/bin/env python3
"""ABP simulation with deterministic packet drops using SimPy.

Stdout: JSONL KPI events only (per spec)
Stderr: logs/debug only
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from typing import Any, Dict, Optional

import simpy


# -----------------------------
# Output (stdout) event emitter
# -----------------------------

def emit_event(env: simpy.Environment, entity: str, event: str, payload: Dict[str, Any]) -> None:
    """Emit a single KPI event record to stdout as JSONL."""
    record = {
        "time": float(f"{env.now:.2f}"),
        "entity": entity,
        "event": event,
        "payload": payload,
    }
    sys.stdout.write(json.dumps(record) + "\n")
    sys.stdout.flush()


# -----------------------------
# Data structures
# -----------------------------


@dataclass(frozen=True)
class DataPacket:
    seq_num: int
    bit: int  # 0 or 1


@dataclass(frozen=True)
class AckPacket:
    bit: int  # 0 or 1


# -----------------------------
# Subnet (channel) with deterministic drop model
# -----------------------------


class Subnet:
    """Unidirectional channel with fixed delay and deterministic drop."""

    def __init__(
        self,
        env: simpy.Environment,
        *,
        channel: str,  # "forward" or "backward"
        delay: float,
        seed: int,
        out_store: simpy.Store,
        logger: logging.Logger,
    ):
        self.env = env
        self.channel = channel
        self.delay = float(delay)
        self.x = int(seed)
        self.out_store = out_store
        self.log = logger

    def put(self, packet: Any) -> None:
        """Packet arrives at subnet; decide drop/pass immediately."""
        self.x = (17 * self.x + 11) % 100
        behavior = "drop" if self.x < 10 else "pass"

        emit_event(
            self.env,
            "subnet",
            "packet_get",
            {"behavior": behavior, "channel": self.channel, "noise_value": int(self.x)},
        )

        if behavior == "pass":
            self.env.process(self._deliver(packet))

    def _deliver(self, packet: Any):
        yield self.env.timeout(self.delay)
        yield self.out_store.put(packet)


# -----------------------------
# Receiver
# -----------------------------


class Receiver:
    def __init__(
        self,
        env: simpy.Environment,
        *,
        in_store: simpy.Store,
        subnet_back: Subnet,
        receiver_delay: float,
        logger: logging.Logger,
    ):
        self.env = env
        self.in_store = in_store
        self.subnet_back = subnet_back
        self.receiver_delay = float(receiver_delay)
        self.log = logger

        self.busy: bool = False
        self.current: Optional[DataPacket] = None
        self.buffer: Optional[DataPacket] = None  # capacity 1

        env.process(self._rx_loop())

    def _rx_loop(self):
        while True:
            pkt = yield self.in_store.get()
            assert isinstance(pkt, DataPacket)

            if not self.busy:
                self.busy = True
                self.current = pkt
                self.env.process(self._process_current_and_buffer())
            else:
                # Busy: buffer capacity 1; only first arrival is stored.
                if self.buffer is None:
                    self.buffer = pkt

    def _process_current_and_buffer(self):
        while self.current is not None:
            pkt = self.current

            emit_event(
                self.env,
                "receiver",
                "delay_start",
                {"type": "processing", "duration": float(f"{self.receiver_delay:.2f}")},
            )
            yield self.env.timeout(self.receiver_delay)

            # Successfully received after processing
            emit_event(
                self.env,
                "receiver",
                "packet_received",
                {"seq_num": int(pkt.seq_num), "bit": int(pkt.bit)},
            )

            # Immediately send ACK with same bit
            self.subnet_back.put(AckPacket(bit=int(pkt.bit)))

            # Next packet: if buffered, process immediately; otherwise go idle.
            if self.buffer is not None:
                self.current = self.buffer
                self.buffer = None
            else:
                self.current = None
                self.busy = False


# -----------------------------
# Sender
# -----------------------------


class Sender:
    def __init__(
        self,
        env: simpy.Environment,
        *,
        total_packets: int,
        in_ack_store: simpy.Store,
        subnet_fwd: Subnet,
        sender_delay: float,
        timeout: float,
        logger: logging.Logger,
    ):
        self.env = env
        self.total_packets = int(total_packets)
        self.in_ack_store = in_ack_store
        self.subnet_fwd = subnet_fwd
        self.sender_delay = float(sender_delay)
        self.timeout = float(timeout)
        self.log = logger

        # Sender state (used by ack listener)
        self.current_bit: int = 0
        self.waiting_for_ack: bool = False
        self.valid_ack_event: Optional[simpy.Event] = None

        env.process(self._ack_listener())
        env.process(self._send_loop())

    def _ack_listener(self):
        while True:
            ack = yield self.in_ack_store.get()
            assert isinstance(ack, AckPacket)

            is_valid = bool(
                self.waiting_for_ack
                and (self.valid_ack_event is not None)
                and (not self.valid_ack_event.triggered)
                and (int(ack.bit) == int(self.current_bit))
            )

            emit_event(
                self.env,
                "sender",
                "ack_received",
                {"ack_bit": int(ack.bit), "is_valid": bool(is_valid)},
            )

            if is_valid and self.valid_ack_event is not None and not self.valid_ack_event.triggered:
                # Mark ACK received for the currently awaited packet.
                self.waiting_for_ack = False
                self.valid_ack_event.succeed()

    def _send_loop(self):
        bit = 0
        for seq in range(1, self.total_packets + 1):
            self.current_bit = int(bit)
            self.waiting_for_ack = False
            self.valid_ack_event = self.env.event()

            is_retry = False
            while not self.valid_ack_event.triggered:
                # Preparation delay (can be pre-empted by a late valid ACK if retrying)
                emit_event(
                    self.env,
                    "sender",
                    "delay_start",
                    {"type": "preparation", "duration": float(f"{self.sender_delay:.2f}")},
                )

                prep = self.env.timeout(self.sender_delay)
                if self.waiting_for_ack:
                    yield prep | self.valid_ack_event
                    if self.valid_ack_event.triggered:
                        break
                else:
                    yield prep

                # Send packet
                emit_event(
                    self.env,
                    "sender",
                    "packet_sent",
                    {"seq_num": int(seq), "bit": int(bit), "is_retry": bool(is_retry)},
                )
                self.subnet_fwd.put(DataPacket(seq_num=int(seq), bit=int(bit)))

                # Start/continue waiting for valid ACK
                self.waiting_for_ack = True
                is_retry = True

                tmo = self.env.timeout(self.timeout)
                yield tmo | self.valid_ack_event
                # If timeout fired first, loop will retry.

            # Next packet uses alternating bit
            bit = 1 - bit


def _run_until(env: simpy.Environment, until_time: float):
    """Ensure the environment has an event at until_time so env.run reaches it."""
    yield env.timeout(float(until_time))


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

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    log = logging.getLogger("abp")

    env = simpy.Environment()

    # Stores between components
    fwd_out = simpy.Store(env)  # subnet1 -> receiver
    back_out = simpy.Store(env)  # subnet2 -> sender

    subnet1 = Subnet(
        env,
        channel="forward",
        delay=float(args.channel_delay),
        seed=int(args.seed),
        out_store=fwd_out,
        logger=log,
    )
    subnet2 = Subnet(
        env,
        channel="backward",
        delay=float(args.channel_delay),
        seed=int(args.seed),
        out_store=back_out,
        logger=log,
    )

    Receiver(
        env,
        in_store=fwd_out,
        subnet_back=subnet2,
        receiver_delay=float(args.receiver_delay),
        logger=log,
    )

    Sender(
        env,
        total_packets=int(args.total_packets),
        in_ack_store=back_out,
        subnet_fwd=subnet1,
        sender_delay=float(args.sender_delay),
        timeout=float(args.timeout),
        logger=log,
    )

    # Force the simulation to progress up to simulate_time even if idle.
    env.process(_run_until(env, float(args.simulate_time)))
    env.run(until=float(args.simulate_time))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
