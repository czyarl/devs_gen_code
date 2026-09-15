"""Sender model implementing Alternating Bit Protocol (ABP) for file packet uploads."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Sender(Atomic):
    """Sender model for file packet uploads using ABP."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        preparation_delay: float,
        timeout_duration: float,
        link_delay: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.preparation_delay = preparation_delay
        self.timeout_duration = timeout_duration
        self.link_delay = link_delay
        self.add_in_port(Port(dict, "control_cmd"))
        self.add_in_port(Port(dict, "ack_from_server"))
        self.add_out_port(Port(dict, "data_to_server"))
        # Internal state
        self.total_packets_to_send = 0
        self.packets_remaining = 0
        self.sequence_number = 1
        self.expected_ack_bit = 0
        self.is_sending = False
        self.current_bit = 0
        self.is_retry = False
        self.outstanding = False

    def _write_event(self, event_type: str, payload: dict) -> None:
        """Write a JSONL event to stdout."""
        print(json.dumps({
            "timestamp_ms": get_current_time(),
            "model": "sender",
            "type": event_type,
            "val": payload,
        }), flush=True)

    def _begin_preparation(self) -> None:
        """Begin the preparation phase before sending a packet."""
        self._write_event("preparation_started", {
            "duration": self.preparation_delay,
        })
        self.hold_in("PREPARING", self.preparation_delay)

    def initialize(self):
        self.total_packets_to_send = 0
        self.packets_remaining = 0
        self.sequence_number = 1
        self.expected_ack_bit = 0
        self.is_sending = False
        self.current_bit = 0
        self.is_retry = False
        self.outstanding = False
        self.passivate("IDLE")

    def deltext(self, e):
        # Handle control command
        for cmd in self.input["control_cmd"].values:
            added = cmd.get("added", 0)
            total_remaining = cmd.get("total_remaining", 0)
            self.total_packets_to_send += added
            self.packets_remaining += added
            self._write_event("control_cmd", {
                "added": added,
                "total_remaining": total_remaining,
            })
            if not self.is_sending and self.packets_remaining > 0:
                self.is_sending = True
                self._begin_preparation()
            else:
                self.continuef(e)
        # Handle ACK from server
        for ack in self.input["ack_from_server"].values:
            ack_bit = ack.get("bit", -1)
            is_valid = self.outstanding and ack_bit == self.expected_ack_bit
            if is_valid:
                self.outstanding = False
                self._write_event("ack_received", {
                    "bit": ack_bit,
                })
                # On correct ACK, flip bit, increment seq, update packets_remaining
                self.expected_ack_bit = 1 - self.expected_ack_bit
                self.sequence_number += 1
                self.packets_remaining -= 1
                if self.packets_remaining <= 0:
                    self.is_sending = False
                    self.passivate("IDLE")
                else:
                    self._begin_preparation()
            else:
                self.continuef(e)

    def lambdaf(self):
        if self.phase == "OUTPUT_READY":
            packet = {
                "seq": self.sequence_number,
                "bit": self.current_bit,
            }
            self.output["data_to_server"].add(packet)
            self._write_event("packet_sent", {
                "seq": self.sequence_number,
                "bit": self.current_bit,
                "is_retry": self.is_retry,
            })

    def deltint(self):
        if self.phase == "PREPARING":
            # Preparation ended; schedule a distinct zero-delay output phase.
            self.hold_in("OUTPUT_READY", 0.0)
        elif self.phase == "OUTPUT_READY":
            self.outstanding = True
            self.current_bit = self.expected_ack_bit
            self.hold_in("WAITING_FOR_ACK", self.timeout_duration)
        elif self.phase == "WAITING_FOR_ACK":
            # Timeout occurred, retry sending
            self.is_retry = True
            self._write_event("timeout", {
                "seq": self.sequence_number,
            })
            self._begin_preparation()
        else:
            self.passivate("IDLE")

    def exit(self):
        pass