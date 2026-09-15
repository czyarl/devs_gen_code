"""Atomic DEVS model for SubnetA1 with 3s FIFO delay."""

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class SubnetA1(Atomic):
    """Provides reliable FIFO 3s delay between Sender and Server.

    Receives data packets from Sender via data_in port, retains each packet
    for exactly 3 seconds, then forwards the same packet to Server via data_out
    port. All packets are forwarded in the order they were received,
    preserving their sequence number and control bit. The model has no internal
    state beyond the queued packet, and operates entirely on the simulation
    clock. On startup, it does not emit any initial signal. It handles only one
    packet at a time, and ignores any new packet until the current one has been
    forwarded. The model terminates when the simulation ends.
    """

    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "data_out"))
        self.in_flight = None

    def initialize(self):
        self.in_flight = None
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return

        for packet in self.input["data_in"].values:
            self.in_flight = dict(packet)
            self.hold_in("PROCESSING", self.delay)
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "PROCESSING" and self.in_flight is not None:
            self.output["data_out"].add(dict(self.in_flight))

    def deltint(self):
        self.in_flight = None
        self.passivate("IDLE")

    def exit(self):
        pass