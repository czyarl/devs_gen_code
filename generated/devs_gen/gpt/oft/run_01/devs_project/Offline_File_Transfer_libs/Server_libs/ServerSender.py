"""
Atomic DEVS model: ServerSender

Implements the download-side Alternating Bit Protocol (ABP) gating for the Server.
External IO: write-only JSONL events to stdout.
"""

import json
import sys
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class ServerSender(Atomic):
    """
    Atomic DEVS egress forwarder implementing download-side ABP gating.

    Ports:
      Inputs:
        - request_in: {'allowed': bool}
        - receiver_ack_in: {'bit': int}
        - storage_push_in: {'seq': int, 'bit': int}
      Outputs:
        - download_data_out: {'seq': int, 'bit': int}
    """

    MODEL_ID = "server_sender"

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Ports (must match locked contract)
        self.add_in_port(Port(dict, "request_in"))
        self.add_in_port(Port(dict, "receiver_ack_in"))
        self.add_in_port(Port(dict, "storage_push_in"))
        self.add_out_port(Port(dict, "download_data_out"))

        # State
        self.download_allowed: bool = False
        self.fifo_queue: deque = deque()
        self.waiting_for_ack: bool = False
        self.in_flight_packet: dict | None = None

        # Internal output preparation
        self._pending_forward_packet: dict | None = None

    # ---------- helpers ----------

    @staticmethod
    def _now_ms() -> float:
        # Simulation clock uses milliseconds as time unit.
        return float(get_current_time())

    def _emit_stdout_event(self, event_type: str, val: dict) -> None:
        record = {
            "timestamp_ms": self._now_ms(),
            "model": self.MODEL_ID,
            "type": event_type,
            "val": val,
        }
        print(json.dumps(record), flush=True)

    def _can_forward(self) -> bool:
        return (self.download_allowed is True) and (not self.waiting_for_ack) and (len(self.fifo_queue) > 0)

    def _schedule_forward_attempt_if_possible(self) -> None:
        # If already scheduled to forward, do not reschedule.
        if self.phase == "FORWARD" and self.sigma == 0.0:
            return
        if self._can_forward():
            self.hold_in("FORWARD", 0.0)
        else:
            self.passivate("WAITING")

    # ---------- DEVS methods ----------

    def initialize(self):
        self.download_allowed = False
        self.waiting_for_ack = False
        self.in_flight_packet = None
        self.fifo_queue = deque()
        self._pending_forward_packet = None
        self.passivate("WAITING")

    def deltext(self, e: float):
        # Preserve remaining time if currently active; then process inputs.
        if self.sigma != float("inf"):
            self.continuef(e)

        # 1) request_in
        for msg in self.input["request_in"].values:
            allowed = bool(msg.get("allowed", False))
            self.download_allowed = allowed
            self._emit_stdout_event("download_valve_change", {"allowed": allowed})

            if allowed:
                # If now allowed and not waiting, attempt immediate forward if queue non-empty.
                if not self.waiting_for_ack and len(self.fifo_queue) > 0:
                    self.hold_in("FORWARD", 0.0)
                else:
                    # Keep current schedule if any; otherwise remain waiting.
                    if self.sigma == float("inf"):
                        self.passivate("WAITING")
            else:
                # Graceful stop: do not cancel in-flight; just prevent new sends.
                if self.waiting_for_ack:
                    # Continue waiting for ACK; no internal event needed.
                    self.passivate("WAITING")
                else:
                    self.passivate("WAITING")

        # 2) storage_push_in
        for pkt in self.input["storage_push_in"].values:
            # Enqueue unchanged
            self.fifo_queue.append(pkt)
            if self.download_allowed and (not self.waiting_for_ack):
                self.hold_in("FORWARD", 0.0)

        # 3) receiver_ack_in
        for ack in self.input["receiver_ack_in"].values:
            bit = int(ack.get("bit"))
            self._emit_stdout_event("ack_received_from_receiver", {"bit": bit})

            if self.waiting_for_ack and self.in_flight_packet is not None:
                in_flight_bit = int(self.in_flight_packet.get("bit"))
                if bit == in_flight_bit:
                    self.waiting_for_ack = False
                    self.in_flight_packet = None
                    if self.download_allowed and len(self.fifo_queue) > 0:
                        self.hold_in("FORWARD", 0.0)
                    else:
                        self.passivate("WAITING")
                else:
                    # Ignore for protocol progress
                    self.passivate("WAITING")
            else:
                # Not waiting: ignore for protocol progress
                self.passivate("WAITING")

        # If no inputs arrived, keep current schedule; otherwise, the above set phase.
        # Ensure we don't remain in an active phase with negative sigma.
        if self.sigma != float("inf") and self.sigma < 0.0:
            self.hold_in(self.phase, 0.0)

    def lambdaf(self):
        # Only emit DEVS outputs here.
        if self.phase == "FORWARD":
            if self._pending_forward_packet is not None:
                self.output["download_data_out"].add(self._pending_forward_packet)

    def deltint(self):
        if self.phase == "FORWARD":
            # Decide and prepare exactly one forward at this internal event.
            self._pending_forward_packet = None

            if self._can_forward():
                pkt = self.fifo_queue.popleft()
                self._pending_forward_packet = pkt

                # External IO: packet_forwarded at same simulation time as output
                self._emit_stdout_event(
                    "packet_forwarded",
                    {"seq": int(pkt.get("seq")), "bit": int(pkt.get("bit"))},
                )

                # Enter waiting state for ACK
                self.waiting_for_ack = True
                self.in_flight_packet = pkt

            # After forwarding (or if couldn't), schedule next step.
            # Cannot forward again until ACK clears waiting_for_ack.
            self.passivate("WAITING")
            return

        self.passivate("WAITING")

    def exit(self):
        # No special termination action required.
        pass