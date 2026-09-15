"""Atomic DEVS model for SubnetB: Reliable, FIFO network with fixed 3s delay."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class SubnetB(Atomic):
    """Simulate reliable, FIFO network transmission with a fixed 3000ms delay.

    Handles two independent unidirectional channels:
    - Server-to-Receiver (Data)
    - Receiver-to-Server (ACK)
    """

    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay

        # Input Ports
        self.add_in_port(Port(dict, "in_from_server"))
        self.add_in_port(Port(dict, "in_from_receiver"))

        # Output Ports
        self.add_out_port(Port(dict, "out_to_receiver"))
        self.add_out_port(Port(dict, "out_to_server"))

        # State: Priority queue of (delivery_time, payload, destination_port_name)
        self.pending = []

    def initialize(self):
        self.pending = []
        self.passivate("IDLE")

    def _reschedule_from_pending(self) -> None:
        """Update sigma based on the earliest packet in the queue."""
        if not self.pending:
            self.passivate("IDLE")
            return

        now = get_current_time()
        # Find the earliest delivery time
        next_time = min(item[0] for item in self.pending)
        self.hold_in("WAITING", max(0.0, next_time - now))

    def deltext(self, e):
        """Handle incoming packets from Server or Receiver."""
        now = get_current_time()

        # Process packets from Server (Data) -> goes to Receiver
        for packet in self.input["in_from_server"].values:
            payload = dict(packet)
            delivery_time = now + self.delay
            # Store with destination info
            self.pending.append((delivery_time, payload, "out_to_receiver"))

        # Process packets from Receiver (ACK) -> goes to Server
        for packet in self.input["in_from_receiver"].values:
            payload = dict(packet)
            delivery_time = now + self.delay
            # Store with destination info
            self.pending.append((delivery_time, payload, "out_to_server"))

        self._reschedule_from_pending()

    def lambdaf(self):
        """Emit packets scheduled for the current simulation time."""
        if self.phase != "WAITING":
            return

        now = get_current_time()

        for delivery_time, payload, dest_port in self.pending:
            if delivery_time <= now:
                # Forward to the appropriate output port
                self.output[dest_port].add(dict(payload))

    def deltint(self):
        """Remove delivered packets and reschedule the next one."""
        now = get_current_time()

        # Keep only packets scheduled for the future
        self.pending = [
            (delivery_time, payload, dest_port)
            for delivery_time, payload, dest_port in self.pending
            if delivery_time > now
        ]

        self._reschedule_from_pending()

    def exit(self):
        pass