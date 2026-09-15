from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json
import sys


class SubnetA2(Atomic):
    """Provides reliable FIFO 3s delay between Server and Sender.

    Receives ACK packets from Server via ack_in port and forwards them to
    Sender after a 3-second delay. Maintains packet ordering and reliability.
    On receipt of an ACK packet, stores it and schedules its delivery to the
    output port after exactly 3000 simulation milliseconds. Does not modify
    packet contents. Starts immediately upon simulation start. No internal
    state beyond the delayed packet queue. Handles only one packet at a time,
    queuing subsequent packets in FIFO order. Terminates gracefully at
    simulation end.
    """

    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "ack_out"))
        self.in_flight = None

    def initialize(self):
        self.in_flight = None
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return

        for packet in self.input["ack_in"].values:
            self.in_flight = dict(packet)
            self.hold_in("PROCESSING", self.delay)
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "PROCESSING" and self.in_flight is not None:
            self.output["ack_out"].add(dict(self.in_flight))

    def deltint(self):
        self.in_flight = None
        self.passivate("IDLE")

    def exit(self):
        pass