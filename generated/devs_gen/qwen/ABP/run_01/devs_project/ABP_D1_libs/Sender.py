"""Sender model implementing the Alternating Bit Protocol with timeout and feedback handling."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Sender(Atomic):
    """Autonomously start at time 0.0, prepare and send one numbered packet with alternating control bit (0,1,0,1...), then wait for matching feedback. Schedule a timeout after sending; on timeout expiry, retry the same packet and restart the timer. On matching feedback receipt, cancel the timeout or pending retry and advance to the next packet. Stop after sending total_packets. Emit JSONL records for delay_start, packet_sent, and ack_received events."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        total_packets: int,
        preparation_delay: float,
        timeout: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.total_packets = total_packets
        self.preparation_delay = preparation_delay
        self.timeout = timeout
        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "packet_out"))
        self.current_seq = 1
        self.current_bit = 0
        self.is_retry = False
        self.outstanding = False

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "entity": "sender",
            "event": event,
            "payload": payload,
        }), flush=True)

    def _begin_preparation(self) -> None:
        # Emit delay_start event at the start of preparation
        self._write_event("delay_start", {
            "type": "preparation",
            "duration": self.preparation_delay,
        })
        self.hold_in("PREPARING", self.preparation_delay)

    def initialize(self):
        self.current_seq = 1
        self.current_bit = 0
        self.is_retry = False
        self.outstanding = False
        if self.total_packets > 0:
            self._begin_preparation()
        else:
            self.passivate("DONE")

    def deltext(self, e):
        accepted = False
        for ack in self.input["ack_in"].values:
            is_valid = self.outstanding and ack.get("ack_bit") == self.current_bit
            self._write_event("ack_received", {
                "ack_bit": ack.get("ack_bit"),
                "is_valid": is_valid,
            })
            accepted = accepted or is_valid

        if accepted:
            # Matching late feedback also cancels a retry being prepared.
            self.outstanding = False
            self.is_retry = False
            self.current_seq += 1
            self.current_bit = 1 - self.current_bit  # alternate 0,1,0,1...
            if self.current_seq > self.total_packets:
                self.passivate("DONE")
            else:
                self._begin_preparation()
        else:
            self.continuef(e)

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return
        packet = {
            "seq_num": self.current_seq,
            "bit": self.current_bit,
            "is_retry": self.is_retry,
        }
        self.output["packet_out"].add(packet)
        self._write_event("packet_sent", dict(packet))

    def deltint(self):
        if self.phase == "PREPARING":
            # Preparation ended; schedule a distinct zero-delay output phase.
            self.hold_in("OUTPUT_READY", 0.0)
        elif self.phase == "OUTPUT_READY":
            self.outstanding = True
            self.hold_in("WAITING_FOR_FEEDBACK", self.timeout)
        elif self.phase == "WAITING_FOR_FEEDBACK":
            self.is_retry = True
            self._begin_preparation()
        else:
            self.passivate("DONE")

    def exit(self):
        pass