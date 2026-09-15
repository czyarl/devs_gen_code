#!/usr/bin/env python3
import argparse
import sys
import json
import logging
import simpy

# Optional (allowed by prompt); not required for execution.
try:
    import xdevs  # noqa: F401
except Exception:
    xdevs = None  # type: ignore


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )


class JsonlEmitter:
    def __init__(self, env: simpy.Environment):
        self.env = env

    def emit(self, entity: str, event: str, payload: dict) -> None:
        t = float(f"{self.env.now:.2f}")
        rec = {
            "time": t,
            "entity": entity,
            "event": event,
            "payload": payload,
        }
        sys.stdout.write(json.dumps(rec) + "\n")
        sys.stdout.flush()


class Subnet:
    """
    Uni-directional channel with deterministic drop/pass fate using:
      x_new = (17*x_old + 11) mod 100
      drop if x_new < 10 else pass after channel_delay
    """

    def __init__(self, env: simpy.Environment, emitter: JsonlEmitter, channel: str, seed: int, channel_delay: float):
        self.env = env
        self.emitter = emitter
        self.channel = channel  # "forward" or "backward"
        self.channel_delay = float(channel_delay)
        self.x = int(seed)
        self.in_store = simpy.Store(env)

        self._deliver_fn = None  # set via connect()
        self.env.process(self._run())

    def connect(self, deliver_fn):
        """deliver_fn(packet_dict) -> simpy.Event (e.g., Store.put())"""
        self._deliver_fn = deliver_fn

    def send(self, packet: dict) -> simpy.Event:
        """Packet arrives at subnet immediately at current sim time."""
        return self.in_store.put(packet)

    def _run(self):
        if self._deliver_fn is None:
            # Will still work once connect() is called before any packet arrives.
            pass

        while True:
            pkt = yield self.in_store.get()

            # Fate determination immediately on arrival
            x_new = (17 * self.x + 11) % 100
            self.x = x_new

            behavior = "drop" if x_new < 10 else "pass"
            self.emitter.emit(
                entity="subnet",
                event="packet_get",
                payload={"behavior": behavior, "channel": self.channel, "noise_value": int(x_new)},
            )

            if behavior == "drop":
                continue

            # Transmit after fixed latency
            yield self.env.timeout(self.channel_delay)

            if self._deliver_fn is None:
                raise RuntimeError("Subnet deliver function not connected.")

            # Deliver (arrival at destination)
            yield self._deliver_fn(pkt)


class Receiver:
    """
    Receiver with:
    - processing delay before accepting packet
    - buffer capacity 1 while busy; extra arrivals are discarded
    - after processing, sends ACK(bit) back immediately via subnet2
    """

    def __init__(self, env: simpy.Environment, emitter: JsonlEmitter, receiver_delay: float):
        self.env = env
        self.emitter = emitter
        self.receiver_delay = float(receiver_delay)

        self.inbox = simpy.Store(env)  # deliveries from forward subnet

        self._busy = False
        self._current = None
        self._buffer = None
        self._has_packet = simpy.Event(env)

        self._ack_subnet = None  # set via connect_ack_subnet()
        self.env.process(self._arrival_listener())
        self.env.process(self._processor())

    def connect_ack_subnet(self, ack_subnet: Subnet):
        self._ack_subnet = ack_subnet

    def put(self, packet: dict) -> simpy.Event:
        return self.inbox.put(packet)

    def _arrival_listener(self):
        while True:
            pkt = yield self.inbox.get()

            if not self._busy and self._current is None:
                self._current = pkt
                if not self._has_packet.triggered:
                    self._has_packet.succeed()
            else:
                # Busy or current already set -> buffer first only
                if self._buffer is None:
                    self._buffer = pkt
                else:
                    # Discard silently (no required event)
                    pass

    def _processor(self):
        while True:
            if self._current is None:
                self._has_packet = simpy.Event(self.env)
                yield self._has_packet

            # Drain current and any buffered packets sequentially
            while self._current is not None:
                pkt = self._current
                self._current = None
                self._busy = True

                # Start processing delay
                self.emitter.emit(
                    entity="receiver",
                    event="delay_start",
                    payload={"type": "processing", "duration": float(self.receiver_delay)},
                )
                yield self.env.timeout(self.receiver_delay)

                # Successfully received (after processing)
                self.emitter.emit(
                    entity="receiver",
                    event="packet_received",
                    payload={"seq_num": int(pkt["seq_num"]), "bit": int(pkt["bit"])},
                )

                # Send ACK immediately (no explicit receiver ACK event required)
                if self._ack_subnet is None:
                    raise RuntimeError("Receiver ACK subnet not connected.")
                ack = {"type": "ack", "bit": int(pkt["bit"])}
                yield self._ack_subnet.send(ack)

                self._busy = False

                # If one packet buffered, process it immediately next
                if self._buffer is not None:
                    self._current = self._buffer
                    self._buffer = None


class Sender:
    """
    Alternating Bit Protocol (stop-and-wait):
    - prepare delay before each send attempt
    - send packet with seq_num and alternating bit
    - start timeout; retransmit on timeout until valid ACK arrives
    """

    def __init__(
        self,
        env: simpy.Environment,
        emitter: JsonlEmitter,
        total_packets: int,
        sender_delay: float,
        timeout: float,
    ):
        self.env = env
        self.emitter = emitter
        self.total_packets = int(total_packets)
        self.sender_delay = float(sender_delay)
        self.timeout = float(timeout)

        self.inbox = simpy.Store(env)      # raw arrivals from backward subnet
        self.ack_queue = simpy.Store(env)  # internal queue for sender logic

        self._expected_bit = 0
        self._forward_subnet = None  # set via connect_forward_subnet()

        self.env.process(self._ack_listener())
        self.env.process(self._run())

    def connect_forward_subnet(self, forward_subnet: Subnet):
        self._forward_subnet = forward_subnet

    def put_ack(self, packet: dict) -> simpy.Event:
        return self.inbox.put(packet)

    def _ack_listener(self):
        while True:
            ack = yield self.inbox.get()
            ack_bit = int(ack["bit"])
            is_valid = (ack_bit == int(self._expected_bit))
            self.emitter.emit(
                entity="sender",
                event="ack_received",
                payload={"ack_bit": ack_bit, "is_valid": bool(is_valid)},
            )
            yield self.ack_queue.put(ack)

    def _run(self):
        if self._forward_subnet is None:
            # Will still work once connect() is called before first send.
            pass

        for seq_num in range(1, self.total_packets + 1):
            bit = (seq_num - 1) % 2
            self._expected_bit = bit

            acked = False
            is_retry = False

            while not acked:
                # Preparation delay
                self.emitter.emit(
                    entity="sender",
                    event="delay_start",
                    payload={"type": "preparation", "duration": float(self.sender_delay)},
                )
                yield self.env.timeout(self.sender_delay)

                # Send packet
                self.emitter.emit(
                    entity="sender",
                    event="packet_sent",
                    payload={"seq_num": int(seq_num), "bit": int(bit), "is_retry": bool(is_retry)},
                )
                if self._forward_subnet is None:
                    raise RuntimeError("Sender forward subnet not connected.")
                pkt = {"type": "data", "seq_num": int(seq_num), "bit": int(bit)}
                yield self._forward_subnet.send(pkt)

                # Wait until timeout for a valid ACK; ignore invalid ACKs
                sent_time = self.env.now
                deadline = sent_time + self.timeout

                while True:
                    remaining = deadline - self.env.now
                    if remaining <= 0:
                        break

                    get_ev = self.ack_queue.get()
                    to_ev = self.env.timeout(remaining)
                    res = yield get_ev | to_ev

                    if get_ev in res:
                        ack = res[get_ev]
                        if int(ack["bit"]) == int(bit):
                            acked = True
                            break
                        else:
                            # invalid ACK; continue waiting within remaining time
                            continue
                    else:
                        # timeout
                        break

                if not acked:
                    is_retry = True
                    # loop retransmits same packet

        # Done; sender stops automatically (no required event)


def parse_args(argv):
    p = argparse.ArgumentParser(description="ABP simulation with deterministic channel noise (JSONL stdout).")
    p.add_argument("--total_packets", type=int, required=True, help="Total number of packets to send.")
    p.add_argument("--seed", type=int, default=42, help="Initialization seed for both subnets' noise level x.")
    p.add_argument("--timeout", type=int, default=20, help="Sender timeout in ms.")
    p.add_argument("--sender_delay", type=int, default=10, help="Sender preparation delay in ms.")
    p.add_argument("--receiver_delay", type=int, default=10, help="Receiver processing delay in ms.")
    p.add_argument("--channel_delay", type=int, default=3, help="Channel traversal delay in ms.")
    p.add_argument("--simulate_time", type=int, default=1000, help="Total simulation time to run in ms.")
    return p.parse_args(argv)


def main(argv=None) -> int:
    setup_logging()
    args = parse_args(argv if argv is not None else sys.argv[1:])

    env = simpy.Environment()
    emitter = JsonlEmitter(env)

    # Entities
    receiver = Receiver(env, emitter, receiver_delay=args.receiver_delay)
    sender = Sender(env, emitter, total_packets=args.total_packets, sender_delay=args.sender_delay, timeout=args.timeout)

    # Subnets
    forward = Subnet(env, emitter, channel="forward", seed=args.seed, channel_delay=args.channel_delay)
    backward = Subnet(env, emitter, channel="backward", seed=args.seed, channel_delay=args.channel_delay)

    # Wiring
    forward.connect(receiver.put)
    backward.connect(sender.put_ack)
    sender.connect_forward_subnet(forward)
    receiver.connect_ack_subnet(backward)

    # Run
    try:
        env.run(until=float(args.simulate_time))
    except Exception as e:
        logging.exception("Simulation error: %s", e)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())