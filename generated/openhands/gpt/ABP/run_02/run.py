#!/usr/bin/env python3
"""ABP (Alternating Bit Protocol) simulation with deterministic channel loss.

Outputs JSONL event records to stdout as specified in the task prompt.
All non-KPI logs go to stderr.
"""

import argparse
import json
import logging
import sys
import simpy
from dataclasses import dataclass



# -----------------------
# JSONL event output
# -----------------------

def _t(ms: float) -> float:
    """Return a float timestamp rounded to 2 decimals."""
    # Keep as float (JSON number). Rounding improves readability.
    return float(f"{ms:.2f}")


def emit(time_ms: float, entity: str, event: str, payload: dict) -> None:
    rec = {
        "time": _t(time_ms),
        "entity": entity,
        "event": event,
        "payload": payload,
    }
    sys.stdout.write(json.dumps(rec, separators=(",", ":")) + "\n")


# -----------------------
# Data structures
# -----------------------


@dataclass(frozen=True)
class DataPacket:
    seq_num: int
    bit: int  # 0 or 1


@dataclass(frozen=True)
class AckPacket:
    bit: int  # 0 or 1


# -----------------------
# Subnet (channel)
# -----------------------


class Subnet:
    """Unidirectional channel with deterministic interference and fixed delay."""

    def __init__(
        self,
        env: simpy.Environment,
        *,
        channel: str,  # "forward" or "backward"
        delay_ms: float,
        seed: int,
        out_store: simpy.Store,
    ) -> None:
        self.env = env
        self.channel = channel
        self.delay_ms = float(delay_ms)
        self._x = int(seed)
        self.out_store = out_store

    def put(self, packet) -> None:
        """Packet arrives at subnet (fate decided immediately)."""
        x_new = (17 * self._x + 11) % 100
        self._x = x_new
        behavior = "drop" if x_new < 10 else "pass"
        emit(
            self.env.now,
            "subnet",
            "packet_get",
            {
                "behavior": behavior,
                "channel": self.channel,
                "noise_value": x_new,
            },
        )

        if behavior == "pass":
            self.env.process(self._deliver_after_delay(packet))

    def _deliver_after_delay(self, packet):
        yield self.env.timeout(self.delay_ms)
        yield self.out_store.put(packet)


# -----------------------
# Receiver
# -----------------------


class Receiver:
    """Receiver with processing delay and a buffer of capacity 1.

    While busy processing one packet, it may buffer *at most one* additional
    arriving packet. If more arrive, only the first is stored.
    """

    def __init__(
        self,
        env: simpy.Environment,
        *,
        processing_delay_ms: float,
        subnet_back: Subnet,
    ) -> None:
        self.env = env
        self.processing_delay_ms = float(processing_delay_ms)
        self.subnet_back = subnet_back

        # Arrival endpoint for the forward subnet.
        self.inbox: simpy.Store = simpy.Store(env)

        self._busy = False
        self._buffer: DataPacket | None = None

    def start(self) -> None:
        self.env.process(self._arrival_loop())

    def _arrival_loop(self):
        while True:
            pkt: DataPacket = yield self.inbox.get()

            if not self._busy:
                self._busy = True
                self.env.process(self._process_chain(pkt))
                continue

            # Busy: buffer capacity is 1.
            if self._buffer is None:
                self._buffer = pkt
            else:
                # Drop silently (no event type defined for this).
                pass

    def _process_chain(self, first_pkt: DataPacket):
        pkt: DataPacket | None = first_pkt
        while pkt is not None:
            emit(
                self.env.now,
                "receiver",
                "delay_start",
                {"type": "processing", "duration": float(self.processing_delay_ms)},
            )
            yield self.env.timeout(self.processing_delay_ms)

            emit(
                self.env.now,
                "receiver",
                "packet_received",
                {"seq_num": int(pkt.seq_num), "bit": int(pkt.bit)},
            )

            # Immediately send ACK with the same bit.
            self.subnet_back.put(AckPacket(bit=pkt.bit))

            # If one packet was buffered during the busy period, process it next.
            pkt = self._buffer
            self._buffer = None

        self._busy = False


# -----------------------
# Sender
# -----------------------


class Sender:
    """Stop-and-wait sender with preparation delay and timeout retransmissions."""

    def __init__(
        self,
        env: simpy.Environment,
        *,
        total_packets: int,
        preparation_delay_ms: float,
        timeout_ms: float,
        subnet_fwd: Subnet,
        ack_inbox: simpy.Store,
    ) -> None:
        self.env = env
        self.total_packets = int(total_packets)
        self.preparation_delay_ms = float(preparation_delay_ms)
        self.timeout_ms = float(timeout_ms)
        self.subnet_fwd = subnet_fwd
        self.ack_inbox = ack_inbox

        # Sender state visible to ACK handler.
        self._awaiting_ack = False
        self._current_bit: int | None = None
        self._ack_ok_event: simpy.Event | None = None

    def start(self) -> None:
        self.env.process(self._ack_handler())
        self.env.process(self._run())

    def _ack_handler(self):
        while True:
            ack: AckPacket = yield self.ack_inbox.get()
            # Validity depends on the *current* expected bit and whether we are awaiting an ACK.
            is_valid = (
                self._awaiting_ack
                and self._current_bit is not None
                and int(ack.bit) == int(self._current_bit)
            )
            emit(
                self.env.now,
                "sender",
                "ack_received",
                {"ack_bit": int(ack.bit), "is_valid": bool(is_valid)},
            )

            if is_valid and self._ack_ok_event is not None and not self._ack_ok_event.triggered:
                self._ack_ok_event.succeed(ack)

    def _run(self):
        for seq_num in range(1, self.total_packets + 1):
            bit = (seq_num - 1) % 2  # first bit is 0
            pkt = DataPacket(seq_num=seq_num, bit=bit)

            self._awaiting_ack = False
            self._current_bit = bit
            self._ack_ok_event = None

            is_retry = False

            while True:
                # Preparation delay (interruptible if ACK arrives while awaiting).
                emit(
                    self.env.now,
                    "sender",
                    "delay_start",
                    {"type": "preparation", "duration": float(self.preparation_delay_ms)},
                )

                delay_ev = self.env.timeout(self.preparation_delay_ms)
                if self._awaiting_ack and self._ack_ok_event is not None:
                    res = yield delay_ev | self._ack_ok_event
                    if self._ack_ok_event in res:
                        # ACK received while preparing a retry; move on.
                        self._awaiting_ack = False
                        break
                else:
                    yield delay_ev

                # Send the packet into the forward subnet.
                emit(
                    self.env.now,
                    "sender",
                    "packet_sent",
                    {"seq_num": int(pkt.seq_num), "bit": int(pkt.bit), "is_retry": bool(is_retry)},
                )
                self.subnet_fwd.put(pkt)

                # Start (or continue) waiting for ACK.
                if not self._awaiting_ack:
                    self._awaiting_ack = True
                    self._ack_ok_event = self.env.event()

                # Wait for valid ACK or timeout.
                timeout_ev = self.env.timeout(self.timeout_ms)
                res = yield timeout_ev | self._ack_ok_event
                if self._ack_ok_event in res:
                    self._awaiting_ack = False
                    break

                # Timeout: retransmit
                is_retry = True

        # Sender stops automatically after sending the batch.


# -----------------------
# Main
# -----------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ABP simulation with deterministic subnet loss")
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

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(levelname)s:%(name)s:%(message)s",
    )
    log = logging.getLogger("abp")

    if args.total_packets < 0:
        log.error("--total_packets must be >= 0")
        return 2
    if args.simulate_time <= 0:
        log.error("--simulate_time must be > 0")
        return 2

    env = simpy.Environment()

    # Endpoint stores.
    sender_ack_inbox = simpy.Store(env)

    # Create receiver first to get its inbox store.
    receiver = Receiver(
        env,
        processing_delay_ms=args.receiver_delay,
        subnet_back=None,  # placeholder, set after subnet created
    )

    subnet_forward = Subnet(
        env,
        channel="forward",
        delay_ms=args.channel_delay,
        seed=args.seed,
        out_store=receiver.inbox,
    )

    subnet_backward = Subnet(
        env,
        channel="backward",
        delay_ms=args.channel_delay,
        seed=args.seed,
        out_store=sender_ack_inbox,
    )

    # Wire receiver back subnet.
    receiver.subnet_back = subnet_backward

    sender = Sender(
        env,
        total_packets=args.total_packets,
        preparation_delay_ms=args.sender_delay,
        timeout_ms=args.timeout,
        subnet_fwd=subnet_forward,
        ack_inbox=sender_ack_inbox,
    )

    receiver.start()
    sender.start()

    env.run(until=float(args.simulate_time))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
