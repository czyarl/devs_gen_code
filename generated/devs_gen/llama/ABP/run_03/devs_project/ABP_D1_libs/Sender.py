"""Complete pattern: Send packets sequentially and wait for ACKs."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Sender(Atomic):
    """Implement the Sender's behavior."""

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
        self.add_in_port(Port(dict, "packet_in"))
        self.add_out_port(Port(dict, "packet_sent"))
        self.add_out_port(Port(dict, "ack_received"))

        self.current_packet = None
        self.current_bit = 0
        self.current_try = 0
        self.outstanding = False

    def initialize(self):
        self.current_packet = 1
        self.current_bit = 0
        self.current_try = 0
        self.outstanding = False
        self.phase = "SENDING"
        self.send_packet()

    def deltext(self, e):
        for packet in self.input["packet_in"].values:
            if not self.outstanding:
                self.hold_in(self.phase, e)

    def lambdaf(self):
        if self.phase == "SENDING":
            self.output["packet_sent"].add({
                "seq_num": self.current_packet,
                "bit": self.current_bit,
                "is_retry": self.current_try > 0,
            })
            self.outstanding = True
            self.hold_in("WAITING_FOR_ACK", self.timeout)

        elif self.phase == "WAITING_FOR_ACK":
            self.output["packet_sent"].add({
                "seq_num": self.current_packet,
                "bit": self.current_bit,
                "is_retry": self.current_try > 0,
            })
            self.current_try += 1
            self.hold_in("WAITING_FOR_ACK", self.timeout)

    def deltint(self):
        if self.phase == "WAITING_FOR_ACK":
            if self.current_try < 3:
                self.hold_in("SENDING", self.sender_delay)
            else:
                self.passivate("DONE")

        elif self.phase == "SENDING":
            self.hold_in("WAITING_FOR_ACK", self.timeout)

    def exit(self):
        print(json.dumps({
            "time": get_current_time(),
            "entity": "sender",
            "event": "TERMINATED",
            "payload": {},
        }), flush=True)

    def external_io(self):
        print(json.dumps({
            "target": "stdout",
            "content": "Sender terminated.\n",
        }), flush=True)

    def send_packet(self):
        self.phase = "SENDING"