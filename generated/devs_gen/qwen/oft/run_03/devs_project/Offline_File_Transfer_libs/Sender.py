import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Sender(Atomic):
    """Manages the upload process of packets from Sender to Server."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "control"))
        self.add_in_port(Port(dict, "ack"))
        self.add_out_port(Port(dict, "data"))
        self.packets_remaining = 0
        self.sequence_number = 1
        self.expected_bit = 0
        self.is_preparing = False
        self.outstanding_ack = False
        self.preparation_timer = 0.0
        self.timeout_timer = 0.0

    def _write_event(self, event_type: str, payload: dict) -> None:
        print(json.dumps({
            "timestamp_ms": get_current_time(),
            "model": "sender",
            "type": event_type,
            "val": payload,
        }), flush=True)

    def initialize(self):
        self.packets_remaining = 0
        self.sequence_number = 1
        self.expected_bit = 0
        self.is_preparing = False
        self.outstanding_ack = False
        self.passivate("IDLE")

    def deltext(self, e):
        # Process control commands
        for control in self.input["control"].values:
            added = control.get("added", 0)
            total_remaining = control.get("total_remaining", 0)
            self.packets_remaining += added
            self._write_event("control_cmd", {"added": added, "total_remaining": total_remaining})

            # If idle and we have packets to send, start sending
            if self.phase == "IDLE" and self.packets_remaining > 0:
                self.is_preparing = True
                self._write_event("preparation_started", {"duration": 10000})
                self.hold_in("PREPARING", 10000.0)

        # Process ACKs
        for ack in self.input["ack"].values:
            ack_bit = ack.get("bit", -1)
            self._write_event("ack_received", {"bit": ack_bit})
            if self.outstanding_ack and ack_bit == self.expected_bit:
                # Correct ACK received
                self.outstanding_ack = False
                self.expected_bit = 1 - self.expected_bit  # Flip bit
                self.sequence_number += 1
                self.packets_remaining -= 1
                if self.packets_remaining <= 0:
                    # All packets acknowledged, go idle
                    self.passivate("IDLE")
                else:
                    # Continue sending
                    self.is_preparing = True
                    self._write_event("preparation_started", {"duration": 10000})
                    self.hold_in("PREPARING", 10000.0)
            elif self.outstanding_ack and ack_bit != self.expected_bit:
                # Duplicate ACK, ignore
                pass

        self.continuef(e)

    def lambdaf(self):
        if self.phase == "OUTPUT_READY":
            packet = {"seq": self.sequence_number, "bit": self.expected_bit}
            self.output["data"].add(packet)
            self._write_event("packet_sent", {
                "seq": self.sequence_number,
                "bit": self.expected_bit,
                "is_retry": self.is_preparing
            })
        elif self.phase == "TIMEOUT":
            self._write_event("timeout", {"seq": self.sequence_number})
            # Retransmit same packet
            self.is_preparing = True
            self._write_event("preparation_started", {"duration": 10000})
            self.hold_in("PREPARING", 10000.0)

    def deltint(self):
        if self.phase == "PREPARING":
            # Preparation complete, prepare to send packet
            self.hold_in("OUTPUT_READY", 0.0)
        elif self.phase == "OUTPUT_READY":
            self.outstanding_ack = True
            self.hold_in("WAITING_FOR_ACK", 20000.0)
        elif self.phase == "WAITING_FOR_ACK":
            # Timeout occurred
            self.hold_in("TIMEOUT", 0.0)
        else:
            self.passivate("IDLE")

    def exit(self):
        pass