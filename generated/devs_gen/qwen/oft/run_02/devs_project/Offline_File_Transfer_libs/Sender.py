"""Sender model implementing Alternating Bit Protocol (ABP) for file uploads."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Sender(Atomic):
    """Sender model handles file upload operations using the Alternating Bit Protocol (ABP)."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        preparation_delay: float,
        timeout_duration: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.preparation_delay = preparation_delay
        self.timeout_duration = timeout_duration
        self.add_in_port(Port(dict, "control"))
        self.add_in_port(Port(dict, "ack"))
        self.add_out_port(Port(dict, "data_out"))
        self.packets_remaining = 0
        self.seq = 1
        self.bit = 0
        self.outstanding = False
        self.is_retry = False

    def _write_event(self, event_type: str, payload: dict) -> None:
        """Write JSONL record to stdout for each event."""
        print(json.dumps({
            "timestamp_ms": get_current_time(),
            "model": "sender",
            "type": event_type,
            "val": payload,
        }), flush=True)

    def _begin_preparation(self) -> None:
        """Begin the preparation phase before sending a packet."""
        self._write_event("preparation_started", {"duration": self.preparation_delay})
        self.hold_in("PREPARING", self.preparation_delay)

    def initialize(self):
        self.packets_remaining = 0
        self.seq = 1
        self.bit = 0
        self.outstanding = False
        self.is_retry = False
        self.passivate("IDLE")

    def deltext(self, e):
        # Handle control commands
        for control in self.input["control"].values:
            added = control.get("added", 0)
            total_remaining = control.get("total_remaining", 0)
            self.packets_remaining += added
            self._write_event("control_cmd", {
                "added": added,
                "total_remaining": total_remaining,
            })

            # If idle and we have packets to send, start sending
            if self.phase == "IDLE" and self.packets_remaining > 0:
                self._begin_preparation()
            else:
                self.continuef(e)

        # Handle ACKs
        for ack in self.input["ack"].values:
            ack_bit = ack.get("bit", -1)
            is_valid = self.outstanding and ack_bit == self.bit
            if is_valid:
                self.outstanding = False
                self._write_event("ack_received", {"bit": ack_bit})
                self.packets_remaining -= 1
                self.bit = 1 - self.bit  # Flip bit
                self.seq += 1
                if self.packets_remaining <= 0:
                    self.passivate("IDLE")
                else:
                    self._begin_preparation()
            else:
                self.continuef(e)

    def lambdaf(self):
        if self.phase == "OUTPUT_READY":
            packet = {"seq": self.seq, "bit": self.bit, "is_retry": self.is_retry}
            self.output["data_out"].add(packet)
            self._write_event("packet_sent", packet)

    def deltint(self):
        if self.phase == "PREPARING":
            self.hold_in("OUTPUT_READY", 0.0)
        elif self.phase == "OUTPUT_READY":
            self.outstanding = True
            self.hold_in("WAITING_FOR_ACK", self.timeout_duration)
        elif self.phase == "WAITING_FOR_ACK":
            self.is_retry = True
            self._begin_preparation()
        else:
            self.passivate("IDLE")

    def exit(self):
        pass