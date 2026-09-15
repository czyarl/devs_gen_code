"""Complete pattern: prepare and send numbered packets, handle ACKs, and write timestamped JSONL events."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Sender(Atomic):
    """Send packets through Subnet1, handle ACKs from Subnet2, and emit JSONL records."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        total_packets: int,
        timeout: float,
        sender_delay: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.total_packets = total_packets
        self.timeout = timeout
        self.sender_delay = sender_delay
        self.add_in_port(Port(None, "initial_signal"))
        self.add_out_port(Port(dict, "packet_out"))
        self.add_out_port(Port(dict, "ack_received"))
        self.seq_num = 1
        self.bit = 0
        self.is_retry = False
        self.outstanding = False

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "entity": "sender",
            "event": event,
            "payload": payload,
        }), flush=True)

    def initialize(self):
        self.seq_num = 1
        self.bit = 0
        self.is_retry = False
        self.outstanding = False
        self._write_event("delay_start", {
            "type": "preparation",
            "duration": self.sender_delay,
        })
        self.hold_in("PREPARING", self.sender_delay)

    def deltext(self, e):
        accepted = False
        for ack in self.input["ack_received"].values:
            self._write_event("ack_received", {
                "ack_bit": ack.get("ack_bit"),
                "is_valid": ack.get("is_valid"),
            })
            is_valid_ack = self.outstanding and ack.get("is_valid")
            accepted = accepted or is_valid_ack

        if accepted:
            self.outstanding = False
            self.bit = 1 - self.bit
            self.seq_num += 1
            if self.seq_num > self.total_packets:
                self.passivate("DONE")
            else:
                self._write_event("delay_start", {
                    "type": "preparation",
                    "duration": self.sender_delay,
                })
                self.hold_in("PREPARING", self.sender_delay)

        else:
            self.continuef(e)

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return
        packet = {"seq_num": self.seq_num, "bit": self.bit, "is_retry": self.is_retry}
        self.output["packet_out"].add(packet)
        self._write_event("packet_sent", packet)

    def deltint(self):
        if self.phase == "PREPARING":
            self.hold_in("OUTPUT_READY", 0.0)
        elif self.phase == "OUTPUT_READY":
            self.outstanding = True
            self.hold_in("WAITING_FOR_ACK", self.timeout)
        elif self.phase == "WAITING_FOR_ACK":
            self.is_retry = True
            self._write_event("delay_start", {
                "type": "preparation",
                "duration": self.sender_delay,
            })
            self.hold_in("PREPARING", self.sender_delay)
        else:
            self.passivate("DONE")

    def exit(self):
        pass