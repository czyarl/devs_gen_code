"""Complete pattern: Send sequential packets and log each event at its semantic occurrence time."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Sender(Atomic):
    """Send sequential packets and log each event at its semantic occurrence time."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        total_packets: int,
        sender_delay: float,
        timeout: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.total_packets = total_packets
        self.sender_delay = sender_delay
        self.timeout = timeout
        self.add_in_port(Port(dict, "packet_in"))
        self.add_out_port(Port(dict, "packet_out"))
        self.seq_num = 1
        self.bit = 0
        self.is_retry = False
        self.outstanding = False

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "event": event,
            "payload": payload,
        }), flush=True)

    def _begin_preparation(self) -> None:
        # This record belongs to the start of preparation, not its completion.
        self._write_event("delay_start", {
            "type": "preparation",
            "duration": self.sender_delay,
        })
        self.hold_in("PREPARING", self.sender_delay)

    def initialize(self):
        self.seq_num = 1
        self.bit = 0
        self.is_retry = False
        self.outstanding = False
        if self.total_packets > 0:
            self._begin_preparation()
        else:
            self.passivate("DONE")

    def deltext(self, e):
        for ack in self.input["packet_in"].values:
            is_valid = self.outstanding and ack.get("ack_bit") == self.bit
            self._write_event("ack_received", {
                "ack_bit": ack.get("ack_bit"),
                "is_valid": is_valid,
            })
            if is_valid:
                # Matching ACK advances the Sender.
                self.outstanding = False
                self.bit = 1 - self.bit
                self.seq_num += 1
                if self.seq_num > self.total_packets:
                    self.passivate("DONE")
                else:
                    self._begin_preparation()
            self.continuef(e)

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return
        packet = {"seq_num": self.seq_num, "bit": self.bit, "is_retry": self.is_retry}
        self.output["packet_out"].add(packet)
        self._write_event("packet_sent", dict(packet))

    def deltint(self):
        if self.phase == "PREPARING":
            # Preparation ended; schedule a distinct zero-delay output phase.
            self.hold_in("OUTPUT_READY", 0.0)
        elif self.phase == "OUTPUT_READY":
            self.outstanding = True
            self.hold_in("WAITING_FOR_ACK", self.timeout)
        elif self.phase == "WAITING_FOR_ACK":
            self.is_retry = True
            self._begin_preparation()
        else:
            self.passivate("DONE")

    def exit(self):
        pass