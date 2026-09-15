#!/usr/bin/env python3
# run.py - xdevs.py DEVS simulation: Alternating Bit Protocol over deterministic-loss channels

import argparse
import sys
import json
import logging
from collections import deque

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock


# ----------------------------
# Logging / JSONL emitter
# ----------------------------

logger = logging.getLogger("abp_xdevs")


def emit_event(t: float, entity: str, event: str, payload: dict) -> None:
    # Output contract: JSONL to stdout only
    rec = {
        "time": float(t),
        "entity": str(entity),
        "event": str(event),
        "payload": payload if isinstance(payload, dict) else {},
    }
    print(json.dumps(rec, separators=(",", ":")), file=sys.stdout, flush=True)


# ----------------------------
# Atomic Models
# ----------------------------

class Sender(Atomic):
    """
    Stop-and-wait Alternating Bit Protocol sender.
    - Prepares packet with delay (sender_delay) then sends.
    - Waits for ACK; if timeout, retransmits.
    """

    def __init__(self, name: str, parent: Coupled | None,
                 total_packets: int,
                 sender_delay: float,
                 timeout: float):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "in_ack"))
        self.add_out_port(Port(dict, "out_data"))

        self.total_packets = int(total_packets)
        self.sender_delay = float(sender_delay)
        self.timeout = float(timeout)

        # Time tracking
        self.now = 0.0

        # Protocol state
        self.seq_num = 1
        self.bit = 0
        self.done = False

        # Bookkeeping
        self._last_send_was_retry = False

        self.hold_in("INIT", 0.0)

    def initialize(self):
        self.now = 0.0
        self.seq_num = 1
        self.bit = 0
        self.done = False
        self._last_send_was_retry = False

        if self.total_packets <= 0:
            self.done = True
            self.hold_in("DONE", float("inf"))
            return

        # Start preparing first packet immediately at t=0
        emit_event(self.now, "sender", "delay_start", {"type": "preparation", "duration": float(self.sender_delay)})
        self._last_send_was_retry = False
        self.hold_in("PREPARE", self.sender_delay)

    def lambdaf(self):
        t_out = self.now + self.sigma

        if self.phase == "PREPARE":
            pkt = {"kind": "data", "seq_num": int(self.seq_num), "bit": int(self.bit)}
            self.output["out_data"].add(pkt)
            emit_event(
                t_out, "sender", "packet_sent",
                {"seq_num": int(self.seq_num), "bit": int(self.bit), "is_retry": False}
            )

        elif self.phase == "WAIT_ACK":
            # Timeout event triggers retransmission
            if not self.done and self.seq_num <= self.total_packets:
                pkt = {"kind": "data", "seq_num": int(self.seq_num), "bit": int(self.bit)}
                self.output["out_data"].add(pkt)
                emit_event(
                    t_out, "sender", "packet_sent",
                    {"seq_num": int(self.seq_num), "bit": int(self.bit), "is_retry": True}
                )

    def deltint(self):
        # Advance local time to this internal event
        self.now += float(self.sigma)

        if self.phase == "PREPARE":
            # After sending, start waiting for ACK with timeout
            self.hold_in("WAIT_ACK", self.timeout)

        elif self.phase == "WAIT_ACK":
            # Timeout occurred; retransmission already output in lambdaf; restart timer
            if self.done:
                self.hold_in("DONE", float("inf"))
            else:
                self.hold_in("WAIT_ACK", self.timeout)

        else:
            self.hold_in("DONE", float("inf"))

    def deltext(self, e):
        # Advance local time by elapsed time since last transition
        self.now += float(e)

        # Read incoming ACKs (could be multiple in same instant)
        acks = list(self.input["in_ack"].values)

        def is_valid_ack(ack_bit: int) -> bool:
            return (not self.done) and (self.phase == "WAIT_ACK") and (ack_bit == self.bit)

        # Default: keep current phase with remaining time, unless valid ACK triggers next action
        if self.phase in ("PREPARE", "WAIT_ACK"):
            remaining = float(self.sigma) - float(e)
            if remaining < 0.0:
                remaining = 0.0
        else:
            remaining = float("inf")

        for ack in acks:
            try:
                ack_bit = int(ack.get("bit"))
            except Exception:
                continue

            valid = is_valid_ack(ack_bit)
            emit_event(self.now, "sender", "ack_received", {"ack_bit": int(ack_bit), "is_valid": bool(valid)})

            if valid:
                # Advance to next packet
                self.seq_num += 1
                self.bit = 1 - int(self.bit)

                if self.seq_num > self.total_packets:
                    self.done = True
                    self.hold_in("DONE", float("inf"))
                    return

                # Start preparing next packet
                emit_event(self.now, "sender", "delay_start", {"type": "preparation", "duration": float(self.sender_delay)})
                self._last_send_was_retry = False
                self.hold_in("PREPARE", self.sender_delay)
                return

        # No valid ACK processed; keep waiting/preparing with remaining time
        if self.phase == "PREPARE":
            self.hold_in("PREPARE", remaining)
        elif self.phase == "WAIT_ACK":
            self.hold_in("WAIT_ACK", remaining)
        else:
            self.hold_in("DONE", float("inf"))

    def exit(self):
        # No stdout output here (contract)
        logger.debug("Sender exit at t=%.3f", self.now)


class Receiver(Atomic):
    """
    Receiver:
    - Processing delay for each received packet.
    - Capacity-1 buffer while busy; only first buffered packet kept.
    - After processing, emits packet_received event and sends ACK(bit).
    """

    def __init__(self, name: str, parent: Coupled | None, receiver_delay: float):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "in_data"))
        self.add_out_port(Port(dict, "out_ack"))

        self.receiver_delay = float(receiver_delay)

        self.now = 0.0

        self.current_pkt = None  # dict or None
        self.buffer_pkt = None   # dict or None

        self.hold_in("INIT", 0.0)

    def initialize(self):
        self.now = 0.0
        self.current_pkt = None
        self.buffer_pkt = None
        self.hold_in("IDLE", float("inf"))

    def lambdaf(self):
        t_out = self.now + self.sigma

        if self.phase == "BUSY" and self.current_pkt is not None:
            seq_num = int(self.current_pkt.get("seq_num", -1))
            bit = int(self.current_pkt.get("bit", 0))

            # At completion of processing delay: packet is "successfully received"
            emit_event(t_out, "receiver", "packet_received", {"seq_num": seq_num, "bit": bit})

            ack = {"kind": "ack", "bit": bit}
            self.output["out_ack"].add(ack)

    def deltint(self):
        self.now += float(self.sigma)

        if self.phase == "BUSY":
            # Finished processing current
            self.current_pkt = None

            if self.buffer_pkt is not None:
                # Immediately start processing buffered packet
                self.current_pkt = self.buffer_pkt
                self.buffer_pkt = None
                emit_event(self.now, "receiver", "delay_start", {"type": "processing", "duration": float(self.receiver_delay)})
                self.hold_in("BUSY", self.receiver_delay)
            else:
                self.hold_in("IDLE", float("inf"))
        else:
            self.hold_in("IDLE", float("inf"))

    def deltext(self, e):
        self.now += float(e)

        arrivals = list(self.input["in_data"].values)

        if self.phase == "IDLE":
            # If idle, take the first arrival as current and start processing; buffer one extra.
            for msg in arrivals:
                if self.current_pkt is None:
                    self.current_pkt = msg
                    emit_event(self.now, "receiver", "delay_start", {"type": "processing", "duration": float(self.receiver_delay)})
                    self.hold_in("BUSY", self.receiver_delay)
                else:
                    # Shouldn't occur in IDLE once started, but handle gracefully
                    if self.buffer_pkt is None:
                        self.buffer_pkt = msg
            return

        if self.phase == "BUSY":
            # Busy: buffer capacity 1; only store first if empty
            for msg in arrivals:
                if self.buffer_pkt is None:
                    self.buffer_pkt = msg
                else:
                    # Drop silently if buffer full
                    pass

            remaining = float(self.sigma) - float(e)
            if remaining < 0.0:
                remaining = 0.0
            self.hold_in("BUSY", remaining)
            return

        # Fallback
        self.hold_in("IDLE", float("inf"))

    def exit(self):
        logger.debug("Receiver exit at t=%.3f", self.now)


class Subnet(Atomic):
    """
    Unidirectional channel with deterministic noise/loss.
    - On arrival: compute x_new = (17*x_old + 11) mod 100; drop if x_new < 10.
    - If pass: transmit after fixed channel_delay.
    - Supports multiple in-flight packets with a delivery queue.
    """

    def __init__(self, name: str, parent: Coupled | None,
                 channel_delay: float, seed: int, direction: str):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "in_msg"))
        self.add_out_port(Port(dict, "out_msg"))

        self.channel_delay = float(channel_delay)
        self.x = int(seed)
        self.direction = str(direction)  # "forward" or "backward"

        self.now = 0.0
        self.queue = deque()  # items: (deliver_time: float, msg: dict)

        self.hold_in("INIT", 0.0)

    def initialize(self):
        self.now = 0.0
        self.queue.clear()
        self.hold_in("IDLE", float("inf"))

    def _schedule_next(self):
        if not self.queue:
            self.hold_in("IDLE", float("inf"))
            return

        next_t = min(dt for dt, _ in self.queue)
        sigma = float(next_t) - float(self.now)
        if sigma < 0.0:
            sigma = 0.0
        self.hold_in("SEND", sigma)

    def lambdaf(self):
        t_out = self.now + self.sigma
        if self.phase != "SEND":
            return

        # Output all messages due at this time
        due = []
        for dt, msg in self.queue:
            if abs(float(dt) - float(t_out)) <= 1e-9:
                due.append(msg)

        for msg in due:
            self.output["out_msg"].add(msg)

    def deltint(self):
        self.now += float(self.sigma)

        if self.phase == "SEND":
            # Remove delivered messages
            remaining = deque()
            for dt, msg in self.queue:
                if abs(float(dt) - float(self.now)) <= 1e-9:
                    continue
                remaining.append((dt, msg))
            self.queue = remaining

        self._schedule_next()

    def deltext(self, e):
        self.now += float(e)

        arrivals = list(self.input["in_msg"].values)
        for msg in arrivals:
            # Deterministic noise update
            self.x = (17 * int(self.x) + 11) % 100
            behavior = "drop" if self.x < 10 else "pass"

            emit_event(
                self.now, "subnet", "packet_get",
                {"behavior": behavior, "channel": self.direction, "noise_value": int(self.x)}
            )

            if behavior == "pass":
                deliver_t = float(self.now) + float(self.channel_delay)
                self.queue.append((deliver_t, msg))

        self._schedule_next()

    def exit(self):
        logger.debug("Subnet(%s) exit at t=%.3f, queued=%d", self.direction, self.now, len(self.queue))


# ----------------------------
# Coupled System
# ----------------------------

class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None,
                 total_packets: int,
                 seed: int,
                 timeout: float,
                 sender_delay: float,
                 receiver_delay: float,
                 channel_delay: float):
        super().__init__(name)
        self.parent = parent

        sender = Sender("sender", parent=self, total_packets=total_packets,
                        sender_delay=sender_delay, timeout=timeout)
        receiver = Receiver("receiver", parent=self, receiver_delay=receiver_delay)
        subnet_fwd = Subnet("subnet_fwd", parent=self, channel_delay=channel_delay,
                            seed=seed, direction="forward")
        subnet_bwd = Subnet("subnet_bwd", parent=self, channel_delay=channel_delay,
                            seed=seed, direction="backward")

        self.add_component(sender)
        self.add_component(receiver)
        self.add_component(subnet_fwd)
        self.add_component(subnet_bwd)

        # Internal couplings
        self.add_coupling(sender.output["out_data"], subnet_fwd.input["in_msg"])
        self.add_coupling(subnet_fwd.output["out_msg"], receiver.input["in_data"])
        self.add_coupling(receiver.output["out_ack"], subnet_bwd.input["in_msg"])
        self.add_coupling(subnet_bwd.output["out_msg"], sender.input["in_ack"])


# ----------------------------
# Entry Point
# ----------------------------

def main():
    parser = argparse.ArgumentParser(description="ABP over deterministic-loss channels (xdevs.py)")
    parser.add_argument("--total_packets", type=int, required=True, help="Total number of packets to send.")
    parser.add_argument("--seed", type=int, default=42, help="Noise seed for both subnets (x initial value).")
    parser.add_argument("--timeout", type=int, default=20, help="Sender timeout in ms.")
    parser.add_argument("--sender_delay", type=int, default=10, help="Sender preparation delay in ms.")
    parser.add_argument("--receiver_delay", type=int, default=10, help="Receiver processing delay in ms.")
    parser.add_argument("--channel_delay", type=int, default=3, help="Channel delay in ms.")
    parser.add_argument("--simulate_time", type=int, default=1000, help="Total simulation time in ms.")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    root = System(
        name="system",
        parent=None,
        total_packets=args.total_packets,
        seed=args.seed,
        timeout=float(args.timeout),
        sender_delay=float(args.sender_delay),
        receiver_delay=float(args.receiver_delay),
        channel_delay=float(args.channel_delay),
    )

    coord = Coordinator(root, clock=SimulationClock(0.0))
    coord.initialize()
    coord.simulate_time(float(args.simulate_time))


if __name__ == "__main__":
    main()