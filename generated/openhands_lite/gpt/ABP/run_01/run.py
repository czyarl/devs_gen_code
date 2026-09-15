#!/usr/bin/env python3
import argparse
import json
import logging
import sys
from dataclasses import dataclass

import simpy


class JsonlEmitter:
    def __init__(self, stream):
        self._stream = stream

    @staticmethod
    def _t(now: float) -> float:
        return round(float(now), 2)

    def emit(self, time: float, entity: str, event: str, payload: dict) -> None:
        rec = {
            "time": self._t(time),
            "entity": entity,
            "event": event,
            "payload": payload,
        }
        self._stream.write(json.dumps(rec) + "\n")
        self._stream.flush()


@dataclass(frozen=True)
class DataPacket:
    seq_num: int
    bit: int


@dataclass(frozen=True)
class AckPacket:
    bit: int


class Subnet:
    def __init__(
        self,
        env: simpy.Environment,
        emitter: JsonlEmitter,
        *,
        channel: str,
        channel_delay: float,
        seed: int,
        deliver,
    ):
        self.env = env
        self.emitter = emitter
        self.channel = channel
        self.channel_delay = float(channel_delay)
        self._x = int(seed)
        self._deliver = deliver

    def _next_noise(self) -> int:
        self._x = (17 * self._x + 11) % 100
        return self._x

    def send(self, packet) -> None:
        noise_value = self._next_noise()
        behavior = "drop" if noise_value < 10 else "pass"
        self.emitter.emit(
            self.env.now,
            "subnet",
            "packet_get",
            {"behavior": behavior, "channel": self.channel, "noise_value": noise_value},
        )
        if behavior == "pass":
            self.env.process(self._in_flight(packet))

    def _in_flight(self, packet):
        yield self.env.timeout(self.channel_delay)
        self._deliver(packet)


class Receiver:
    def __init__(
        self,
        env: simpy.Environment,
        emitter: JsonlEmitter,
        *,
        receiver_delay: float,
        ack_subnet: Subnet,
    ):
        self.env = env
        self.emitter = emitter
        self.receiver_delay = float(receiver_delay)
        self.ack_subnet = ack_subnet

        self._busy = False
        self._buffered = None
        self._wakeup = env.event()
        self.env.process(self._run())

    def accept(self, packet: DataPacket) -> None:
        if (not self._busy) and self._buffered is None:
            self._buffered = packet
            if not self._wakeup.triggered:
                self._wakeup.succeed()
            return

        if self._buffered is None:
            self._buffered = packet
            return

        # Buffer full: ignore additional packets.

    def _run(self):
        while True:
            if self._buffered is None:
                self._wakeup = self.env.event()
                yield self._wakeup
                continue

            pkt = self._buffered
            self._buffered = None
            self._busy = True

            self.emitter.emit(
                self.env.now,
                "receiver",
                "delay_start",
                {"type": "processing", "duration": float(self.receiver_delay)},
            )
            yield self.env.timeout(self.receiver_delay)
            self.emitter.emit(
                self.env.now,
                "receiver",
                "packet_received",
                {"seq_num": int(pkt.seq_num), "bit": int(pkt.bit)},
            )

            self.ack_subnet.send(AckPacket(bit=int(pkt.bit)))

            self._busy = False


class Sender:
    def __init__(
        self,
        env: simpy.Environment,
        emitter: JsonlEmitter,
        *,
        total_packets: int,
        sender_delay: float,
        timeout: float,
        data_subnet: Subnet,
    ):
        self.env = env
        self.emitter = emitter
        self.total_packets = int(total_packets)
        self.sender_delay = float(sender_delay)
        self.timeout = float(timeout)
        self.data_subnet = data_subnet

        self._ack_in = simpy.Store(env)
        self.env.process(self._run())

    def accept_ack(self, ack: AckPacket) -> None:
        self._ack_in.put(ack)

    def _run(self):
        bit = 0
        for seq in range(1, self.total_packets + 1):
            is_retry = False
            while True:
                self.emitter.emit(
                    self.env.now,
                    "sender",
                    "delay_start",
                    {"type": "preparation", "duration": float(self.sender_delay)},
                )
                yield self.env.timeout(self.sender_delay)

                self.emitter.emit(
                    self.env.now,
                    "sender",
                    "packet_sent",
                    {"seq_num": int(seq), "bit": int(bit), "is_retry": bool(is_retry)},
                )
                self.data_subnet.send(DataPacket(seq_num=int(seq), bit=int(bit)))

                got_valid_ack = False
                timeout_evt = self.env.timeout(self.timeout)
                while True:
                    ack_get = self._ack_in.get()
                    res = yield ack_get | timeout_evt

                    if timeout_evt in res:
                        if not ack_get.triggered:
                            ack_get.cancel()
                        break

                    ack = res[ack_get]
                    is_valid = int(ack.bit) == int(bit)
                    self.emitter.emit(
                        self.env.now,
                        "sender",
                        "ack_received",
                        {"ack_bit": int(ack.bit), "is_valid": bool(is_valid)},
                    )
                    if is_valid:
                        got_valid_ack = True
                        break

                if got_valid_ack:
                    bit = 1 - bit
                    break

                is_retry = True


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="ABP simulation with deterministic subnet noise.")
    p.add_argument("--total_packets", type=int, required=True)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--timeout", type=int, default=20)
    p.add_argument("--sender_delay", type=int, default=10)
    p.add_argument("--receiver_delay", type=int, default=10)
    p.add_argument("--channel_delay", type=int, default=3)
    p.add_argument("--simulate_time", type=int, default=1000)
    return p


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    env = simpy.Environment()
    emitter = JsonlEmitter(sys.stdout)

    sender = None

    def deliver_to_sender(ack: AckPacket):
        sender.accept_ack(ack)

    receiver = None

    def deliver_to_receiver(pkt: DataPacket):
        receiver.accept(pkt)

    # Create entities. Delivery callbacks capture the instances above.
    backward_subnet = Subnet(
        env,
        emitter,
        channel="backward",
        channel_delay=args.channel_delay,
        seed=args.seed,
        deliver=deliver_to_sender,
    )
    receiver = Receiver(
        env,
        emitter,
        receiver_delay=args.receiver_delay,
        ack_subnet=backward_subnet,
    )

    forward_subnet = Subnet(
        env,
        emitter,
        channel="forward",
        channel_delay=args.channel_delay,
        seed=args.seed,
        deliver=deliver_to_receiver,
    )

    sender = Sender(
        env,
        emitter,
        total_packets=args.total_packets,
        sender_delay=args.sender_delay,
        timeout=args.timeout,
        data_subnet=forward_subnet,
    )

    env.run(until=float(args.simulate_time))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
