#!/usr/bin/env python3
import argparse
import json
import logging
import sys
from typing import Any, Dict, Optional

import simpy


class TwoDecimalFloatEncoder(json.JSONEncoder):
    def iterencode(self, o, _one_shot=False):
        def floatstr(
            value,
            allow_nan=self.allow_nan,
            _inf=float("inf"),
            _neginf=-float("inf"),
        ):
            if value != value:
                text = "NaN"
            elif value == _inf:
                text = "Infinity"
            elif value == _neginf:
                text = "-Infinity"
            else:
                return format(value, ".2f")
            if not allow_nan:
                raise ValueError("Out of range float values are not JSON compliant")
            return text

        _iterencode = json.encoder._make_iterencode(
            markers={},
            _default=self.default,
            _encoder=json.encoder.encode_basestring,
            _indent=self.indent,
            _floatstr=floatstr,
            _key_separator=self.key_separator,
            _item_separator=self.item_separator,
            _sort_keys=self.sort_keys,
            _skipkeys=self.skipkeys,
            _one_shot=_one_shot,
        )
        return _iterencode(o, 0)


def emit(env: simpy.Environment, entity: str, event: str, payload: Dict[str, Any]) -> None:
    record = {
        "time": float(env.now),
        "entity": entity,
        "event": event,
        "payload": payload,
    }
    sys.stdout.write(json.dumps(record, cls=TwoDecimalFloatEncoder) + "\n")
    sys.stdout.flush()


class Subnet:
    def __init__(
        self,
        env: simpy.Environment,
        *,
        channel: str,
        seed: int,
        channel_delay: float,
        out_store: simpy.Store,
    ) -> None:
        self.env = env
        self.channel = channel  # "forward" or "backward"
        self.x = int(seed)
        self.channel_delay = float(channel_delay)
        self.out_store = out_store

    def put(self, packet: Dict[str, Any]) -> None:
        x_new = (17 * self.x + 11) % 100
        self.x = x_new

        behavior = "drop" if x_new < 10 else "pass"
        emit(
            self.env,
            "subnet",
            "packet_get",
            {"behavior": behavior, "channel": self.channel, "noise_value": int(x_new)},
        )

        if behavior == "pass":
            self.env.process(self._deliver(packet))

    def _deliver(self, packet: Dict[str, Any]):
        yield self.env.timeout(self.channel_delay)
        yield self.out_store.put(packet)


class Receiver:
    def __init__(
        self,
        env: simpy.Environment,
        *,
        in_store: simpy.Store,
        receiver_delay: float,
        backward_subnet: Subnet,
    ) -> None:
        self.env = env
        self.in_store = in_store
        self.receiver_delay = float(receiver_delay)
        self.backward_subnet = backward_subnet

        self._busy = False
        self._buffer: Optional[Dict[str, Any]] = None

        self.env.process(self._run())

    def _run(self):
        while True:
            pkt = yield self.in_store.get()
            self._on_arrival(pkt)

    def _on_arrival(self, packet: Dict[str, Any]) -> None:
        if not self._busy:
            self._busy = True
            self.env.process(self._process(packet))
            return

        if self._buffer is None:
            self._buffer = packet

    def _process(self, packet: Dict[str, Any]):
        emit(
            self.env,
            "receiver",
            "delay_start",
            {"type": "processing", "duration": float(self.receiver_delay)},
        )
        yield self.env.timeout(self.receiver_delay)

        seq_num = int(packet.get("seq_num", -1))
        bit = int(packet.get("bit", 0))
        emit(self.env, "receiver", "packet_received", {"seq_num": seq_num, "bit": bit})

        self.backward_subnet.put({"type": "ack", "bit": bit})

        self._busy = False
        if self._buffer is not None:
            nxt = self._buffer
            self._buffer = None
            self._busy = True
            self.env.process(self._process(nxt))


class Sender:
    def __init__(
        self,
        env: simpy.Environment,
        *,
        ack_store: simpy.Store,
        total_packets: int,
        sender_delay: float,
        timeout: float,
        forward_subnet: Subnet,
    ) -> None:
        self.env = env
        self.ack_store = ack_store
        self.total_packets = int(total_packets)
        self.sender_delay = float(sender_delay)
        self.timeout = float(timeout)
        self.forward_subnet = forward_subnet

        self.env.process(self._run())

    def _run(self):
        for seq_num in range(1, self.total_packets + 1):
            bit = (seq_num - 1) % 2
            attempt = 0

            while True:
                is_retry = attempt > 0
                emit(
                    self.env,
                    "sender",
                    "delay_start",
                    {"type": "preparation", "duration": float(self.sender_delay)},
                )
                yield self.env.timeout(self.sender_delay)

                emit(
                    self.env,
                    "sender",
                    "packet_sent",
                    {"seq_num": seq_num, "bit": bit, "is_retry": bool(is_retry)},
                )
                self.forward_subnet.put({"type": "data", "seq_num": seq_num, "bit": bit})

                deadline = float(self.env.now + self.timeout)
                got_valid = False

                while True:
                    remaining = deadline - float(self.env.now)
                    if remaining <= 0:
                        break

                    ack_ev = self.ack_store.get()
                    to_ev = self.env.timeout(remaining)
                    res = yield ack_ev | to_ev

                    if ack_ev in res:
                        ack = res[ack_ev]
                        ack_bit = int(ack.get("bit", -1))
                        is_valid = ack_bit == bit
                        emit(
                            self.env,
                            "sender",
                            "ack_received",
                            {"ack_bit": ack_bit, "is_valid": bool(is_valid)},
                        )
                        if is_valid:
                            got_valid = True
                            break
                    else:
                        try:
                            ack_ev.cancel()
                        except Exception:
                            pass
                        break

                if got_valid:
                    break

                attempt += 1


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ABP simulation with deterministic loss")
    p.add_argument("--total_packets", type=int, required=True)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--timeout", type=int, default=20)
    p.add_argument("--sender_delay", type=int, default=10)
    p.add_argument("--receiver_delay", type=int, default=10)
    p.add_argument("--channel_delay", type=int, default=3)
    p.add_argument("--simulate_time", type=int, default=1000)
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[%(levelname)s] %(message)s")

    env = simpy.Environment()

    sender_ack_store: simpy.Store = simpy.Store(env)
    receiver_in_store: simpy.Store = simpy.Store(env)

    backward_subnet = Subnet(
        env,
        channel="backward",
        seed=args.seed,
        channel_delay=float(args.channel_delay),
        out_store=sender_ack_store,
    )

    Receiver(
        env,
        in_store=receiver_in_store,
        receiver_delay=float(args.receiver_delay),
        backward_subnet=backward_subnet,
    )

    forward_subnet = Subnet(
        env,
        channel="forward",
        seed=args.seed,
        channel_delay=float(args.channel_delay),
        out_store=receiver_in_store,
    )

    Sender(
        env,
        ack_store=sender_ack_store,
        total_packets=int(args.total_packets),
        sender_delay=float(args.sender_delay),
        timeout=float(args.timeout),
        forward_subnet=forward_subnet,
    )

    env.run(until=float(args.simulate_time))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
