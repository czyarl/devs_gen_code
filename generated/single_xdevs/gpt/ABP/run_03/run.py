#!/usr/bin/env python3
import argparse
import sys
import json
import logging
import math
from typing import Any, Deque, Dict, List, Optional, Tuple

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock


# -----------------------------
# Logging / JSONL KPI emission
# -----------------------------
def _t2(time_ms: float) -> float:
    # Keep at least 2 decimals and ensure JSON number is float
    return float(f"{time_ms:.2f}")


def emit(time_ms: float, entity: str, event: str, payload: Dict[str, Any]) -> None:
    rec = {
        "time": _t2(time_ms),
        "entity": entity,
        "event": event,
        "payload": payload,
    }
    print(json.dumps(rec), file=sys.stdout, flush=True)


# -----------------------------
# Sender (ABP Stop-and-Wait)
# -----------------------------
class Sender(Atomic):
    def __init__(
        self,
        name: str,
        parent: Optional[Coupled],
        total_packets: int,
        sender_delay: float,
        timeout: float,
    ):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "pkt_out"))

        self.total_packets = int(total_packets)
        self.sender_delay = float(sender_delay)
        self.timeout = float(timeout)

        # Local time tracking
        self.now: float = 0.0

        # ABP state
        self.seq_num: int = 1
        self.bit: int = 0
        self.retry_flag: bool = False  # whether next send is retry

        self.hold_in("IDLE", math.inf)

    def initialize(self):
        self.now = 0.0
        self.seq_num = 1
        self.bit = 0
        self.retry_flag = False

        if self.total_packets <= 0:
            self.hold_in("DONE", math.inf)
            return

        # Start preparing first packet immediately at t=0
        emit(self.now, "sender", "delay_start", {"type": "preparation", "duration": float(self.sender_delay)})
        self.hold_in("PREP", self.sender_delay)

    def lambdaf(self):
        # Internal outputs occur at time (now + sigma)
        t_event = self.now + self.sigma

        if self.phase == "SEND":
            pkt = {"seq_num": int(self.seq_num), "bit": int(self.bit)}
            self.output["pkt_out"].add(pkt)
            emit(
                t_event,
                "sender",
                "packet_sent",
                {"seq_num": int(self.seq_num), "bit": int(self.bit), "is_retry": bool(self.retry_flag)},
            )
        # No other outputs

    def deltint(self):
        # Advance time to internal transition moment
        self.now += self.sigma

        if self.phase == "PREP":
            # After preparation, schedule immediate send
            self.retry_flag = False
            self.hold_in("SEND", 0.0)

        elif self.phase == "SEND":
            # After sending, wait for ACK or timeout
            self.hold_in("WAIT", self.timeout)

        elif self.phase == "WAIT":
            # Timeout: retransmit immediately
            self.retry_flag = True
            self.hold_in("SEND", 0.0)

        elif self.phase == "DONE":
            self.hold_in("DONE", math.inf)

        else:
            # Fallback
            self.hold_in("DONE", math.inf)

    def deltext(self, e):
        # External transition at time now + e
        self.now += float(e)

        # Process ACKs only while waiting
        if self.phase != "WAIT":
            # Keep current schedule (reduced by elapsed time)
            remaining = self.sigma - float(e) if self.sigma != math.inf else math.inf
            if remaining < 0:
                remaining = 0.0
            self.hold_in(self.phase, remaining)
            return

        # Remaining time until timeout if we stay in WAIT
        remaining = self.sigma - float(e)
        if remaining < 0:
            remaining = 0.0

        ack_values = list(self.input["ack_in"].values)
        handled_valid = False

        for ack in ack_values:
            if not isinstance(ack, dict):
                continue
            ack_bit = ack.get("bit", None)
            if ack_bit not in (0, 1):
                continue

            is_valid = (int(ack_bit) == int(self.bit))
            emit(self.now, "sender", "ack_received", {"ack_bit": int(ack_bit), "is_valid": bool(is_valid)})

            if is_valid and not handled_valid:
                handled_valid = True
                # Move to next packet
                self.seq_num += 1
                self.bit = 1 - int(self.bit)
                self.retry_flag = False

                if self.seq_num > self.total_packets:
                    self.hold_in("DONE", math.inf)
                else:
                    emit(self.now, "sender", "delay_start", {"type": "preparation", "duration": float(self.sender_delay)})
                    self.hold_in("PREP", self.sender_delay)
                break  # Stop-and-wait: accept first valid ACK only

        if not handled_valid:
            # No valid ACK -> keep waiting with remaining timeout
            self.hold_in("WAIT", remaining)

    def exit(self):
        return


# -----------------------------
# Receiver (buffer capacity 1)
# -----------------------------
class Receiver(Atomic):
    def __init__(
        self,
        name: str,
        parent: Optional[Coupled],
        receiver_delay: float,
    ):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "pkt_in"))
        self.add_out_port(Port(dict, "ack_out"))

        self.receiver_delay = float(receiver_delay)

        self.now: float = 0.0

        self.current_pkt: Optional[Dict[str, Any]] = None
        self.buffered_pkt: Optional[Dict[str, Any]] = None

        self.hold_in("IDLE", math.inf)

    def initialize(self):
        self.now = 0.0
        self.current_pkt = None
        self.buffered_pkt = None
        self.hold_in("IDLE", math.inf)

    def lambdaf(self):
        t_event = self.now + self.sigma

        if self.phase == "BUSY" and self.current_pkt is not None:
            # Processing completes now -> "packet_received" + send ACK immediately
            seq_num = int(self.current_pkt.get("seq_num", -1))
            bit = int(self.current_pkt.get("bit", 0))
            emit(t_event, "receiver", "packet_received", {"seq_num": seq_num, "bit": bit})
            self.output["ack_out"].add({"bit": bit})

    def deltint(self):
        # Advance time to completion of processing
        self.now += self.sigma

        if self.phase == "BUSY":
            # Move buffered packet to processing if exists
            if self.buffered_pkt is not None:
                self.current_pkt = self.buffered_pkt
                self.buffered_pkt = None
                emit(self.now, "receiver", "delay_start", {"type": "processing", "duration": float(self.receiver_delay)})
                self.hold_in("BUSY", self.receiver_delay)
            else:
                self.current_pkt = None
                self.hold_in("IDLE", math.inf)
        else:
            self.hold_in("IDLE", math.inf)

    def deltext(self, e):
        self.now += float(e)

        incoming = list(self.input["pkt_in"].values)

        if not incoming:
            # No input -> keep schedule adjusted
            remaining = self.sigma - float(e) if self.sigma != math.inf else math.inf
            if remaining < 0:
                remaining = 0.0
            self.hold_in(self.phase, remaining)
            return

        # Accept packets with buffer capacity 1 while busy
        if self.phase == "IDLE":
            # Start processing first packet immediately
            first = incoming[0]
            if isinstance(first, dict):
                self.current_pkt = first
                emit(self.now, "receiver", "delay_start", {"type": "processing", "duration": float(self.receiver_delay)})
                self.hold_in("BUSY", self.receiver_delay)
            else:
                self.hold_in("IDLE", math.inf)

            # Remaining packets arrive while busy at same time -> buffer first only
            for msg in incoming[1:]:
                if self.buffered_pkt is None and isinstance(msg, dict):
                    self.buffered_pkt = msg
                else:
                    # drop silently
                    pass
            return

        if self.phase == "BUSY":
            # Still busy; buffer first packet only
            for msg in incoming:
                if self.buffered_pkt is None and isinstance(msg, dict):
                    self.buffered_pkt = msg
                else:
                    pass

            remaining = self.sigma - float(e)
            if remaining < 0:
                remaining = 0.0
            self.hold_in("BUSY", remaining)
            return

        # Fallback
        self.hold_in("IDLE", math.inf)

    def exit(self):
        return


# -----------------------------
# Subnet (deterministic loss + fixed delay)
# -----------------------------
class Subnet(Atomic):
    def __init__(
        self,
        name: str,
        parent: Optional[Coupled],
        channel: str,  # "forward" or "backward"
        seed: int,
        channel_delay: float,
    ):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "in"))
        self.add_out_port(Port(dict, "out"))

        self.channel = str(channel)
        self.x = int(seed)
        self.channel_delay = float(channel_delay)

        self.now: float = 0.0
        self.queue: List[Tuple[float, Dict[str, Any]]] = []  # (ready_time, msg)

        self.hold_in("IDLE", math.inf)

    def initialize(self):
        self.now = 0.0
        self.queue = []
        self.hold_in("IDLE", math.inf)

    def _schedule_next(self):
        if not self.queue:
            self.hold_in("IDLE", math.inf)
            return
        next_ready = min(rt for rt, _ in self.queue)
        sigma = next_ready - self.now
        if sigma < 0:
            sigma = 0.0
        self.hold_in("TX", sigma)

    def lambdaf(self):
        t_event = self.now + self.sigma
        if self.phase != "TX":
            return

        # Output all messages due now
        due = [msg for (rt, msg) in self.queue if rt <= t_event + 1e-9]
        for msg in due:
            self.output["out"].add(msg)

    def deltint(self):
        # Advance to t_event
        self.now += self.sigma

        if self.phase == "TX":
            # Remove due messages
            self.queue = [(rt, msg) for (rt, msg) in self.queue if rt > self.now + 1e-9]
            self._schedule_next()
        else:
            self._schedule_next()

    def deltext(self, e):
        self.now += float(e)

        # Process all arriving packets: fate determined immediately
        for msg in list(self.input["in"].values):
            # Update noise level for each arrival
            x_new = (17 * self.x + 11) % 100
            self.x = x_new

            behavior = "drop" if x_new < 10 else "pass"
            emit(self.now, "subnet", "packet_get", {"behavior": behavior, "channel": self.channel, "noise_value": int(x_new)})

            if behavior == "pass" and isinstance(msg, dict):
                ready_time = self.now + self.channel_delay
                self.queue.append((ready_time, msg))
            else:
                # drop
                pass

        self._schedule_next()

    def exit(self):
        return


# -----------------------------
# Coupled system
# -----------------------------
class System(Coupled):
    def __init__(
        self,
        name: str,
        parent: Optional[Coupled],
        total_packets: int,
        seed: int,
        timeout: float,
        sender_delay: float,
        receiver_delay: float,
        channel_delay: float,
    ):
        super().__init__(name)
        self.parent = parent

        sender = Sender(
            name="sender_model",
            parent=self,
            total_packets=total_packets,
            sender_delay=sender_delay,
            timeout=timeout,
        )
        receiver = Receiver(
            name="receiver_model",
            parent=self,
            receiver_delay=receiver_delay,
        )
        subnet_fwd = Subnet(
            name="subnet_forward",
            parent=self,
            channel="forward",
            seed=seed,
            channel_delay=channel_delay,
        )
        subnet_bwd = Subnet(
            name="subnet_backward",
            parent=self,
            channel="backward",
            seed=seed,
            channel_delay=channel_delay,
        )

        self.add_component(sender)
        self.add_component(receiver)
        self.add_component(subnet_fwd)
        self.add_component(subnet_bwd)

        # Couplings: Sender -> Subnet1 -> Receiver -> Subnet2 -> Sender
        self.add_coupling(sender.output["pkt_out"], subnet_fwd.input["in"])
        self.add_coupling(subnet_fwd.output["out"], receiver.input["pkt_in"])
        self.add_coupling(receiver.output["ack_out"], subnet_bwd.input["in"])
        self.add_coupling(subnet_bwd.output["out"], sender.input["ack_in"])


# -----------------------------
# Entry point
# -----------------------------
def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--total_packets", type=int, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--sender_delay", type=int, default=10)
    parser.add_argument("--receiver_delay", type=int, default=10)
    parser.add_argument("--channel_delay", type=int, default=3)
    parser.add_argument("--simulate_time", type=int, default=1000)
    args = parser.parse_args()

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