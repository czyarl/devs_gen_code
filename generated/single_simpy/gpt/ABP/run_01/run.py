#!/usr/bin/env python3
# run.py

import argparse
import sys
import json
import logging
import simpy


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(message)s",
    )


class JsonlEmitter:
    def __init__(self, env: simpy.Environment):
        self.env = env

    def emit(self, entity: str, event: str, payload: dict) -> None:
        rec = {
            "time": float(round(self.env.now, 2)),
            "entity": entity,
            "event": event,
            "payload": payload,
        }
        sys.stdout.write(json.dumps(rec) + "\n")


class Subnet:
    """
    Deterministic-loss channel with fixed propagation delay.
    Noise update on arrival: x = (17*x + 11) mod 100
    drop if x < 10 else pass after channel_delay
    """

    def __init__(self, env: simpy.Environment, emitter: JsonlEmitter, seed: int, channel_delay: float, channel_name: str):
        self.env = env
        self.emitter = emitter
        self.channel_delay = float(channel_delay)
        self.channel_name = channel_name  # "forward" or "backward"
        self.x = int(seed)
        self.inbox = simpy.Store(env)

    def put(self, packet: dict) -> None:
        self.inbox.put(packet)

    def run(self, outbox: simpy.Store):
        while True:
            pkt = yield self.inbox.get()
            self.x = (17 * self.x + 11) % 100
            behavior = "drop" if self.x < 10 else "pass"
            self.emitter.emit(
                "subnet",
                "packet_get",
                {"behavior": behavior, "channel": self.channel_name, "noise_value": int(self.x)},
            )
            if behavior == "pass":
                self.env.process(self._deliver(pkt, outbox))

    def _deliver(self, pkt: dict, outbox: simpy.Store):
        yield self.env.timeout(self.channel_delay)
        yield outbox.put(pkt)


class Receiver:
    """
    Processing delay per packet; buffer capacity 1 while busy.
    If multiple arrivals while busy: store first, drop the rest.
    After processing, emit packet_received and immediately send ACK with same bit.
    """

    def __init__(
        self,
        env: simpy.Environment,
        emitter: JsonlEmitter,
        receiver_delay: float,
        subnet_back: Subnet,
        sender_inbox: simpy.Store,
    ):
        self.env = env
        self.emitter = emitter
        self.receiver_delay = float(receiver_delay)
        self.subnet_back = subnet_back
        self.sender_inbox = sender_inbox

        self.inbox = simpy.Store(env)
        self.busy = False
        self.buffer = None  # capacity 1

    def put(self, packet: dict) -> None:
        self.inbox.put(packet)

    def run(self):
        while True:
            pkt = yield self.inbox.get()
            if not self.busy:
                self.busy = True
                self.env.process(self._process(pkt))
            else:
                if self.buffer is None:
                    self.buffer = pkt
                else:
                    # Drop silently (no event defined for receiver drops)
                    pass

    def _process(self, pkt: dict):
        self.emitter.emit(
            "receiver",
            "delay_start",
            {"type": "processing", "duration": float(self.receiver_delay)},
        )
        yield self.env.timeout(self.receiver_delay)

        seq_num = int(pkt.get("seq_num", -1))
        bit = int(pkt.get("bit", 0))
        self.emitter.emit(
            "receiver",
            "packet_received",
            {"seq_num": seq_num, "bit": bit},
        )

        # Send ACK immediately after processing completion
        ack = {"bit": bit}
        self.subnet_back.put(ack)

        # Finish and immediately start buffered packet if any
        if self.buffer is not None:
            next_pkt = self.buffer
            self.buffer = None
            self.env.process(self._process(next_pkt))
        else:
            self.busy = False


class Sender:
    """
    Alternating Bit Protocol sender with preparation delay and retransmission on timeout.
    Uses a shared valid_ack_event per packet; accepts a valid ACK if its bit matches current packet bit.
    """

    def __init__(
        self,
        env: simpy.Environment,
        emitter: JsonlEmitter,
        total_packets: int,
        sender_delay: float,
        timeout: float,
        subnet_fwd: Subnet,
    ):
        self.env = env
        self.emitter = emitter
        self.total_packets = int(total_packets)
        self.sender_delay = float(sender_delay)
        self.timeout = float(timeout)
        self.subnet_fwd = subnet_fwd

        self.ack_inbox = simpy.Store(env)

        self._expected_bit = 0
        self._valid_ack_event = None  # type: simpy.Event | None
        self._done = False

    def put_ack(self, ack: dict) -> None:
        self.ack_inbox.put(ack)

    def ack_listener(self):
        while True:
            ack = yield self.ack_inbox.get()
            ack_bit = int(ack.get("bit", 0))
            expected = self._expected_bit
            ev = self._valid_ack_event
            is_valid = bool((ev is not None) and (not ev.triggered) and (ack_bit == expected))
            self.emitter.emit(
                "sender",
                "ack_received",
                {"ack_bit": ack_bit, "is_valid": is_valid},
            )
            if is_valid:
                ev.succeed(True)

    def run(self):
        seq_num = 1
        bit = 0

        while seq_num <= self.total_packets:
            self._expected_bit = bit
            self._valid_ack_event = self.env.event()

            is_retry = False
            got_ack = False

            while not got_ack:
                # Preparation delay (can be preempted by a valid ACK arriving late)
                self.emitter.emit(
                    "sender",
                    "delay_start",
                    {"type": "preparation", "duration": float(self.sender_delay)},
                )
                prep = self.env.timeout(self.sender_delay)
                res = yield simpy.AnyOf(self.env, [prep, self._valid_ack_event])
                if self._valid_ack_event in res.events:
                    got_ack = True
                    break

                # Send packet
                pkt = {"seq_num": seq_num, "bit": bit}
                self.emitter.emit(
                    "sender",
                    "packet_sent",
                    {"seq_num": seq_num, "bit": bit, "is_retry": bool(is_retry)},
                )
                self.subnet_fwd.put(pkt)

                # Wait for ACK or timeout
                to = self.env.timeout(self.timeout)
                res = yield simpy.AnyOf(self.env, [to, self._valid_ack_event])
                if self._valid_ack_event in res.events:
                    got_ack = True
                    break

                # Timeout: retry
                is_retry = True

            # Move to next packet
            seq_num += 1
            bit = 1 - bit

        self._done = True


def parse_args(argv):
    p = argparse.ArgumentParser(description="ABP Reliable Transfer Simulation with Deterministic Loss")
    p.add_argument("--total_packets", type=int, required=True, help="Total number of packets to send")
    p.add_argument("--seed", type=int, default=42, help="Seed for deterministic noise generators")
    p.add_argument("--timeout", type=int, default=20, help="Sender timeout (ms)")
    p.add_argument("--sender_delay", type=int, default=10, help="Sender preparation delay (ms)")
    p.add_argument("--receiver_delay", type=int, default=10, help="Receiver processing delay (ms)")
    p.add_argument("--channel_delay", type=int, default=3, help="Channel propagation delay (ms)")
    p.add_argument("--simulate_time", type=int, default=1000, help="Total simulation time (ms)")
    return p.parse_args(argv)


def main(argv=None):
    setup_logging()
    args = parse_args(argv if argv is not None else sys.argv[1:])

    env = simpy.Environment()
    emitter = JsonlEmitter(env)

    # Stores connecting endpoints
    receiver_inbox = simpy.Store(env)  # packets delivered to receiver
    sender_ack_inbox = simpy.Store(env)  # acks delivered to sender

    # Subnets
    subnet_fwd = Subnet(env, emitter, seed=args.seed, channel_delay=args.channel_delay, channel_name="forward")
    subnet_back = Subnet(env, emitter, seed=args.seed, channel_delay=args.channel_delay, channel_name="backward")

    # Receiver and Sender
    receiver = Receiver(
        env,
        emitter,
        receiver_delay=args.receiver_delay,
        subnet_back=subnet_back,
        sender_inbox=sender_ack_inbox,
    )
    sender = Sender(
        env,
        emitter,
        total_packets=args.total_packets,
        sender_delay=args.sender_delay,
        timeout=args.timeout,
        subnet_fwd=subnet_fwd,
    )

    # Wiring: subnet outputs to endpoint inboxes
    env.process(subnet_fwd.run(receiver.inbox))
    env.process(subnet_back.run(sender.ack_inbox))

    # Endpoint processes
    env.process(receiver.run())
    env.process(sender.ack_listener())
    env.process(sender.run())

    env.run(until=float(args.simulate_time))


if __name__ == "__main__":
    main()