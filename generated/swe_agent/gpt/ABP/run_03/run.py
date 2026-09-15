#!/usr/bin/env python3
"""ABP_03 - Alternating Bit Protocol simulation using SimPy.

Implements a Sender, Receiver, and two deterministic-loss uni-directional
channels (subnets). Emits required KPI events as JSON Lines (JSONL) to stdout.
All other logging goes to stderr.

Time unit: 1.0 simulation time unit = 1 millisecond.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Optional

import simpy


def _configure_logging() -> logging.Logger:
    logger = logging.getLogger("abp")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


LOGGER = _configure_logging()


def emit_jsonl(env: simpy.Environment, entity: str, event: str, payload: Dict[str, Any]) -> None:
    """Emit one JSONL record to stdout with required schema."""
    record = {
        "time": float(f"{env.now:.2f}"),
        "entity": entity,
        "event": event,
        "payload": payload,
    }
    sys.stdout.write(json.dumps(record) + "\n")
    sys.stdout.flush()


@dataclass(frozen=True)
class DataPacket:
    seq_num: int
    bit: int


@dataclass(frozen=True)
class AckPacket:
    ack_bit: int


class Subnet:
    """Uni-directional channel with deterministic packet loss and fixed latency."""

    def __init__(
        self,
        env: simpy.Environment,
        *,
        channel: str,  # "forward" or "backward"
        seed: int,
        channel_delay: float,
        in_store: simpy.Store,
        out_store: simpy.Store,
    ):
        self.env = env
        self.channel = channel
        self.channel_delay = float(channel_delay)
        self.in_store = in_store
        self.out_store = out_store
        self.x = int(seed)
        self.env.process(self._run())

    def _step_noise(self) -> int:
        self.x = (17 * self.x + 11) % 100
        return self.x

    def _run(self):
        while True:
            pkt = yield self.in_store.get()

            noise_value = self._step_noise()
            behavior = "drop" if noise_value < 10 else "pass"

            emit_jsonl(
                self.env,
                entity="subnet",
                event="packet_get",
                payload={"behavior": behavior, "channel": self.channel, "noise_value": int(noise_value)},
            )

            if behavior == "drop":
                continue

            yield self.env.timeout(self.channel_delay)
            yield self.out_store.put(pkt)


class Receiver:
    """Receiver with processing delay and a capacity-1 buffer."""

    def __init__(
        self,
        env: simpy.Environment,
        *,
        receiver_delay: float,
        in_store: simpy.Store,
        ack_out_store: simpy.Store,
    ):
        self.env = env
        self.receiver_delay = float(receiver_delay)
        self.in_store = in_store
        self.ack_out_store = ack_out_store

        # Capacity 1 buffer: store first arrival while busy, drop others.
        self._buffer: Deque[DataPacket] = deque(maxlen=1)
        self._buffer_event: simpy.Event = env.event()

        self.env.process(self._intake())
        self.env.process(self._worker())

    def _notify_buffer_nonempty(self) -> None:
        if not self._buffer_event.triggered:
            self._buffer_event.succeed()

    def _reset_buffer_event(self) -> None:
        self._buffer_event = self.env.event()

    def _intake(self):
        while True:
            pkt = yield self.in_store.get()
            if len(self._buffer) == 0:
                self._buffer.append(pkt)
                self._notify_buffer_nonempty()
            else:
                # Buffer full; ignore further arrivals.
                pass

    def _worker(self):
        while True:
            if len(self._buffer) == 0:
                yield self._buffer_event
                self._reset_buffer_event()
                continue

            pkt = self._buffer.popleft()
            emit_jsonl(
                self.env,
                entity="receiver",
                event="delay_start",
                payload={"type": "processing", "duration": float(f"{self.receiver_delay:.2f}")},
            )
            yield self.env.timeout(self.receiver_delay)

            emit_jsonl(
                self.env,
                entity="receiver",
                event="packet_received",
                payload={"seq_num": int(pkt.seq_num), "bit": int(pkt.bit)},
            )

            # Immediately send ACK back with the same bit.
            yield self.ack_out_store.put(AckPacket(ack_bit=int(pkt.bit)))


class Sender:
    """Stop-and-wait sender with preparation delay and timeout retransmission."""

    def __init__(
        self,
        env: simpy.Environment,
        *,
        total_packets: int,
        timeout: float,
        sender_delay: float,
        data_out_store: simpy.Store,
        ack_in_store: simpy.Store,
    ):
        self.env = env
        self.total_packets = int(total_packets)
        self.timeout = float(timeout)
        self.sender_delay = float(sender_delay)
        self.data_out_store = data_out_store
        self.ack_in_store = ack_in_store

        self.env.process(self._run())

    def _prep_and_send(self, seq_num: int, bit: int, is_retry: bool):
        emit_jsonl(
            self.env,
            entity="sender",
            event="delay_start",
            payload={"type": "preparation", "duration": float(f"{self.sender_delay:.2f}")},
        )
        yield self.env.timeout(self.sender_delay)

        emit_jsonl(
            self.env,
            entity="sender",
            event="packet_sent",
            payload={"seq_num": int(seq_num), "bit": int(bit), "is_retry": bool(is_retry)},
        )
        yield self.data_out_store.put(DataPacket(seq_num=int(seq_num), bit=int(bit)))

    def _run(self):
        seq_num = 1
        bit = 0

        while seq_num <= self.total_packets:
            is_retry = False
            while True:
                yield from self._prep_and_send(seq_num, bit, is_retry)

                timeout_ev = self.env.timeout(self.timeout)

                while True:
                    ack_ev = self.ack_in_store.get()
                    res = yield ack_ev | timeout_ev

                    if timeout_ev in res:
                        # Cancel the pending Store.get() request so it doesn't
                        # consume a future ACK meant for the retransmission.
                        try:
                            ack_ev.cancel()
                        except Exception:
                            pass
                        is_retry = True
                        break

                    ack = res[ack_ev]
                    ack_bit = int(getattr(ack, "ack_bit", -1))
                    is_valid = ack_bit == int(bit)

                    emit_jsonl(
                        self.env,
                        entity="sender",
                        event="ack_received",
                        payload={"ack_bit": ack_bit, "is_valid": bool(is_valid)},
                    )

                    if is_valid:
                        seq_num += 1
                        bit = 1 - bit
                        is_retry = False
                        break

                if not is_retry:
                    break


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Alternating Bit Protocol simulation")
    parser.add_argument("--total_packets", type=int, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--sender_delay", type=int, default=10)
    parser.add_argument("--receiver_delay", type=int, default=10)
    parser.add_argument("--channel_delay", type=int, default=3)
    parser.add_argument("--simulate_time", type=int, default=1000)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    env = simpy.Environment()

    # Stores between components.
    sender_to_subnet1 = simpy.Store(env)
    subnet1_to_receiver = simpy.Store(env)

    receiver_to_subnet2 = simpy.Store(env)
    subnet2_to_sender = simpy.Store(env)

    # Channels.
    Subnet(
        env,
        channel="forward",
        seed=args.seed,
        channel_delay=float(args.channel_delay),
        in_store=sender_to_subnet1,
        out_store=subnet1_to_receiver,
    )
    Subnet(
        env,
        channel="backward",
        seed=args.seed,
        channel_delay=float(args.channel_delay),
        in_store=receiver_to_subnet2,
        out_store=subnet2_to_sender,
    )

    Receiver(
        env,
        receiver_delay=float(args.receiver_delay),
        in_store=subnet1_to_receiver,
        ack_out_store=receiver_to_subnet2,
    )

    Sender(
        env,
        total_packets=int(args.total_packets),
        timeout=float(args.timeout),
        sender_delay=float(args.sender_delay),
        data_out_store=sender_to_subnet1,
        ack_in_store=subnet2_to_sender,
    )

    env.run(until=float(args.simulate_time))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
