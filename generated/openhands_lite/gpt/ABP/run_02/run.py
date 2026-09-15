#!/usr/bin/env python3
import argparse
import json
import logging
import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import simpy


def _t2(time_value: float) -> float:
    return float(f"{float(time_value):.2f}")


class JsonlEmitter:
    def __init__(self, out_stream):
        self._out = out_stream

    def emit(self, time_value: float, entity: str, event: str, payload: Dict[str, Any]) -> None:
        record = {
            "time": _t2(time_value),
            "entity": entity,
            "event": event,
            "payload": payload,
        }
        self._out.write(json.dumps(record) + "\n")
        self._out.flush()


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
        *,
        emitter: JsonlEmitter,
        channel: str,
        channel_delay: float,
        seed: int,
        deliver: Callable[[Any], None],
    ):
        if channel not in {"forward", "backward"}:
            raise ValueError("channel must be 'forward' or 'backward'")
        self.env = env
        self.emitter = emitter
        self.channel = channel
        self.channel_delay = float(channel_delay)
        self._deliver = deliver

        self._noise_x = int(seed)
        self._in = simpy.Store(env)
        self._proc = env.process(self._run())

    def send(self, packet: Any) -> None:
        self._in.put(packet)

    def _lcg_next(self) -> int:
        return (17 * self._noise_x + 11) % 100

    def _run(self):
        while True:
            packet = yield self._in.get()
            x_new = self._lcg_next()
            self._noise_x = x_new

            behavior = "drop" if x_new < 10 else "pass"
            self.emitter.emit(
                self.env.now,
                "subnet",
                "packet_get",
                {"behavior": behavior, "channel": self.channel, "noise_value": x_new},
            )

            if behavior == "pass":
                self.env.process(self._deliver_after_delay(packet))

    def _deliver_after_delay(self, packet: Any):
        yield self.env.timeout(self.channel_delay)
        self._deliver(packet)


class Receiver:
    def __init__(
        self,
        env: simpy.Environment,
        *,
        emitter: JsonlEmitter,
        receiver_delay: float,
        backward_subnet: Subnet,
    ):
        self.env = env
        self.emitter = emitter
        self.receiver_delay = float(receiver_delay)
        self.backward_subnet = backward_subnet

        self._buf = simpy.Store(env, capacity=1)
        self._proc = env.process(self._run())

    def receive(self, packet: DataPacket) -> None:
        if len(self._buf.items) >= 1:
            return
        self._buf.put(packet)

    def _run(self):
        while True:
            pkt: DataPacket = yield self._buf.get()
            self.emitter.emit(
                self.env.now,
                "receiver",
                "delay_start",
                {"type": "processing", "duration": _t2(self.receiver_delay)},
            )
            yield self.env.timeout(self.receiver_delay)
            self.emitter.emit(
                self.env.now,
                "receiver",
                "packet_received",
                {"seq_num": pkt.seq_num, "bit": pkt.bit},
            )
            self.backward_subnet.send(AckPacket(bit=pkt.bit))


class Sender:
    def __init__(
        self,
        env: simpy.Environment,
        *,
        emitter: JsonlEmitter,
        total_packets: int,
        sender_delay: float,
        timeout: float,
        forward_subnet: Subnet,
    ):
        self.env = env
        self.emitter = emitter
        self.total_packets = int(total_packets)
        self.sender_delay = float(sender_delay)
        self.timeout = float(timeout)
        self.forward_subnet = forward_subnet

        self._waiting_for_ack: bool = False
        self._current_bit: Optional[int] = None
        self._done_event: Optional[simpy.Event] = None

        self._proc = env.process(self._run())

    def receive_ack(self, packet: AckPacket) -> None:
        is_valid = (
            self._waiting_for_ack
            and self._current_bit is not None
            and int(packet.bit) == int(self._current_bit)
        )
        self.emitter.emit(
            self.env.now,
            "sender",
            "ack_received",
            {"ack_bit": int(packet.bit), "is_valid": bool(is_valid)},
        )

        if is_valid and self._done_event is not None and not self._done_event.triggered:
            self._done_event.succeed()

    def _run(self):
        for seq in range(1, self.total_packets + 1):
            bit = (seq - 1) % 2

            self._waiting_for_ack = True
            self._current_bit = int(bit)
            self._done_event = self.env.event()

            send_count = 0
            while True:
                prep_timeout = self.env.timeout(self.sender_delay)
                self.emitter.emit(
                    self.env.now,
                    "sender",
                    "delay_start",
                    {"type": "preparation", "duration": _t2(self.sender_delay)},
                )
                result = yield simpy.AnyOf(self.env, [self._done_event, prep_timeout])
                if self._done_event in result:
                    break

                self.emitter.emit(
                    self.env.now,
                    "sender",
                    "packet_sent",
                    {"seq_num": seq, "bit": bit, "is_retry": bool(send_count > 0)},
                )
                self.forward_subnet.send(DataPacket(seq_num=seq, bit=bit))
                send_count += 1

                timeout_ev = self.env.timeout(self.timeout)
                result = yield simpy.AnyOf(self.env, [self._done_event, timeout_ev])
                if self._done_event in result:
                    break

            self._waiting_for_ack = False
            self._current_bit = None
            self._done_event = None


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="ABP simulation with deterministic loss")
    parser.add_argument("--total_packets", type=int, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--sender_delay", type=int, default=10)
    parser.add_argument("--receiver_delay", type=int, default=10)
    parser.add_argument("--channel_delay", type=int, default=3)
    parser.add_argument("--simulate_time", type=int, default=1000)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING,
        stream=sys.stderr,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    env = simpy.Environment()
    emitter = JsonlEmitter(sys.stdout)

    sender: Optional[Sender] = None

    def deliver_to_sender(pkt: AckPacket) -> None:
        assert sender is not None
        sender.receive_ack(pkt)

    # Create backward subnet first; receiver needs it.
    backward_subnet = Subnet(
        env,
        emitter=emitter,
        channel="backward",
        channel_delay=float(args.channel_delay),
        seed=int(args.seed),
        deliver=deliver_to_sender,
    )

    receiver: Optional[Receiver] = None

    def deliver_to_receiver(pkt: DataPacket) -> None:
        assert receiver is not None
        receiver.receive(pkt)

    forward_subnet = Subnet(
        env,
        emitter=emitter,
        channel="forward",
        channel_delay=float(args.channel_delay),
        seed=int(args.seed),
        deliver=deliver_to_receiver,
    )

    receiver = Receiver(
        env,
        emitter=emitter,
        receiver_delay=float(args.receiver_delay),
        backward_subnet=backward_subnet,
    )

    sender = Sender(
        env,
        emitter=emitter,
        total_packets=int(args.total_packets),
        sender_delay=float(args.sender_delay),
        timeout=float(args.timeout),
        forward_subnet=forward_subnet,
    )

    env.run(until=float(args.simulate_time))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
