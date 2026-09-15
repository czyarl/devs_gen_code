#!/usr/bin/env python3
"""Reliable data transfer (ABP) with deterministic channel interference.

Discrete-event simulation implemented with SimPy.

Output:
  - stdout: JSONL KPI event records only
  - stderr: diagnostics via logging

Time units:
  1.0 simulation time unit == 1 millisecond.
"""

import argparse
import json
import logging
import sys

import simpy


# --- JSONL output (fixed 2-decimal float rendering) ---
# The spec requires time values to be floats with at least 2 decimal places.
# Python's json.dumps() uses a minimal float representation (e.g., 10.0), so we
# use a custom encoder to render floats with exactly 2 decimals (e.g., 10.00).


class _Fixed2FloatEncoder(json.JSONEncoder):
    def iterencode(self, o, _one_shot=False):
        # Uses CPython's internal encoder factory; stable across Python 3.10+.
        from json.encoder import (
            _make_iterencode,
            encode_basestring,
            encode_basestring_ascii,
        )

        if self.check_circular:
            markers = {}
        else:
            markers = None

        _encoder = encode_basestring_ascii if self.ensure_ascii else encode_basestring

        def floatstr(val, allow_nan=self.allow_nan):
            # Match stdlib semantics for NaN/Infinity handling.
            if val != val:
                text = "NaN"
            elif val == float("inf"):
                text = "Infinity"
            elif val == float("-inf"):
                text = "-Infinity"
            else:
                return format(val, ".2f")
            if not allow_nan:
                raise ValueError("Out of range float values are not JSON compliant")
            return text

        _iterencode = _make_iterencode(
            markers,
            self.default,
            _encoder,
            self.indent,
            floatstr,
            self.key_separator,
            self.item_separator,
            self.sort_keys,
            self.skipkeys,
            _one_shot,
        )
        return _iterencode(o, 0)


def emit(env, entity, event, payload):
    """Emit a single KPI event record to stdout as JSONL."""
    record = {
        "time": float(env.now),
        "entity": str(entity),
        "event": str(event),
        "payload": payload if isinstance(payload, dict) else dict(payload),
    }
    sys.stdout.write(json.dumps(record, cls=_Fixed2FloatEncoder) + "\n")
    sys.stdout.flush()


def make_data_packet(seq_num, bit):
    return {"kind": "data", "seq_num": int(seq_num), "bit": int(bit)}


def make_ack_packet(bit):
    return {"kind": "ack", "bit": int(bit)}


class Subnet:
    """Unidirectional channel with deterministic interference and fixed latency."""

    def __init__(self, env, *, seed, channel_delay, channel_name, deliver_fn):
        self.env = env
        self.x = int(seed)
        self.channel_delay = float(channel_delay)
        self.channel_name = str(channel_name)  # "forward" or "backward"
        self._deliver_fn = deliver_fn

    def send(self, packet):
        # Noise evaluation happens immediately when the packet arrives at the subnet.
        x_new = (17 * self.x + 11) % 100
        self.x = x_new

        behavior = "drop" if x_new < 10 else "pass"
        emit(
            self.env,
            "subnet",
            "packet_get",
            {"behavior": behavior, "channel": self.channel_name, "noise_value": int(x_new)},
        )

        if behavior == "drop":
            return

        # Independent per-packet latency.
        self.env.process(self._deliver_after_delay(packet))

    def _deliver_after_delay(self, packet):
        yield self.env.timeout(self.channel_delay)
        self._deliver_fn(packet)


class Receiver:
    """Receiver with processing delay and a single waiting buffer slot."""

    def __init__(self, env, *, receiver_delay, ack_subnet):
        self.env = env
        self.receiver_delay = float(receiver_delay)
        self.ack_subnet = ack_subnet

        self.busy = False
        self.current = None
        self.buffered = None
        self._wakeup = None

        self.env.process(self._run())

    def on_packet(self, packet):
        # Buffer capacity 1: while busy, store only the first arriving packet.
        if (not self.busy) and (self.current is None):
            self.current = packet
            if self._wakeup is not None and not self._wakeup.triggered:
                self._wakeup.succeed()
            return

        if self.buffered is None:
            self.buffered = packet
        # else: silently drop extra arrivals

    def _run(self):
        while True:
            if self.current is None:
                self._wakeup = self.env.event()
                yield self._wakeup

            self.busy = True
            emit(
                self.env,
                "receiver",
                "delay_start",
                {"type": "processing", "duration": float(self.receiver_delay)},
            )
            yield self.env.timeout(self.receiver_delay)

            pkt = self.current
            emit(
                self.env,
                "receiver",
                "packet_received",
                {"seq_num": int(pkt["seq_num"]), "bit": int(pkt["bit"])},
            )

            # Immediately send ACK with same bit.
            self.ack_subnet.send(make_ack_packet(pkt["bit"]))

            # Move buffered packet (if any) into current.
            if self.buffered is not None:
                self.current = self.buffered
                self.buffered = None
                self.busy = False
                continue

            self.current = None
            self.busy = False


class Sender:
    """Stop-and-wait sender with alternating bit and timeout retransmissions."""

    def __init__(self, env, *, total_packets, sender_delay, timeout, data_subnet):
        self.env = env
        self.total_packets = int(total_packets)
        self.sender_delay = float(sender_delay)
        self.timeout = float(timeout)
        self.data_subnet = data_subnet

        self.seq_num = 1
        self.current_bit = 0
        self._ack_event = None

        self.env.process(self._run())

    def on_ack(self, ack):
        ack_bit = int(ack["bit"])
        is_valid = (
            self._ack_event is not None
            and not self._ack_event.triggered
            and ack_bit == int(self.current_bit)
        )

        emit(
            self.env,
            "sender",
            "ack_received",
            {"ack_bit": int(ack_bit), "is_valid": bool(is_valid)},
        )

        if is_valid:
            self._ack_event.succeed()

    def _run(self):
        while self.seq_num <= self.total_packets:
            self._ack_event = self.env.event()
            is_retry = False

            while not self._ack_event.triggered:
                emit(
                    self.env,
                    "sender",
                    "delay_start",
                    {"type": "preparation", "duration": float(self.sender_delay)},
                )

                # If a late-but-valid ACK arrives while "preparing" a retry, cancel.
                prep_res = yield self._ack_event | self.env.timeout(self.sender_delay)
                if self._ack_event in prep_res:
                    break

                emit(
                    self.env,
                    "sender",
                    "packet_sent",
                    {
                        "seq_num": int(self.seq_num),
                        "bit": int(self.current_bit),
                        "is_retry": bool(is_retry),
                    },
                )

                self.data_subnet.send(make_data_packet(self.seq_num, self.current_bit))

                res = yield self._ack_event | self.env.timeout(self.timeout)
                if self._ack_event in res:
                    break

                is_retry = True

            self.seq_num += 1
            self.current_bit ^= 1


def parse_args(argv):
    p = argparse.ArgumentParser(description="ABP simulation with deterministic channel loss")
    p.add_argument("--total_packets", type=int, required=True)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--timeout", type=int, default=20)
    p.add_argument("--sender_delay", type=int, default=10)
    p.add_argument("--receiver_delay", type=int, default=10)
    p.add_argument("--channel_delay", type=int, default=3)
    p.add_argument("--simulate_time", type=int, default=1000)
    return p.parse_args(argv)


def main(argv):
    args = parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("abp")

    if args.total_packets <= 0:
        raise SystemExit("--total_packets must be > 0")

    env = simpy.Environment()

    sender = None
    receiver = None

    # Receiver -> Sender (ACK) subnet
    def deliver_ack(pkt):
        if sender is not None:
            sender.on_ack(pkt)

    subnet2 = Subnet(
        env,
        seed=args.seed,
        channel_delay=args.channel_delay,
        channel_name="backward",
        deliver_fn=deliver_ack,
    )

    receiver = Receiver(env, receiver_delay=args.receiver_delay, ack_subnet=subnet2)

    # Sender -> Receiver (DATA) subnet
    def deliver_data(pkt):
        if receiver is not None:
            receiver.on_packet(pkt)

    subnet1 = Subnet(
        env,
        seed=args.seed,
        channel_delay=args.channel_delay,
        channel_name="forward",
        deliver_fn=deliver_data,
    )

    sender = Sender(
        env,
        total_packets=args.total_packets,
        sender_delay=args.sender_delay,
        timeout=args.timeout,
        data_subnet=subnet1,
    )

    log.info(
        "Starting simulation: total_packets=%s seed=%s timeout=%s sender_delay=%s receiver_delay=%s channel_delay=%s simulate_time=%s",
        args.total_packets,
        args.seed,
        args.timeout,
        args.sender_delay,
        args.receiver_delay,
        args.channel_delay,
        args.simulate_time,
    )

    env.run(until=float(args.simulate_time))
    log.info("Simulation finished at t=%s", env.now)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
