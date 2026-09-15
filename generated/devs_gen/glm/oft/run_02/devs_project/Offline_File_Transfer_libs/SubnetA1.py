"""Atomic DEVS model for SubnetA1: Reliable FIFO link with fixed delay."""

from xdevs.models import Atomic, Coupled, Port


class SubnetA1(Atomic):
    """Acts as a reliable, First-In-First-Out (FIFO) transmission link with a constant propagation delay."""

    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "data_out"))
        self.queue = []
        self.in_flight = None

    def initialize(self):
        self.queue = []
        self.in_flight = None
        self.passivate("IDLE")

    def _start_next(self) -> None:
        self.in_flight = self.queue.pop(0)
        self.hold_in("TRANSMITTING", self.delay)

    def deltext(self, e: float):
        # Capture the state before processing inputs to preserve the timer of the in-flight packet
        was_transmitting = self.phase == "TRANSMITTING"
        remaining = max(0.0, self.ta() - e) if was_transmitting else None

        # Append all new arrivals to the internal queue
        for packet in self.input["data_in"].values:
            self.queue.append(dict(packet))

        # If idle and queue is now non-empty, start transmitting the head packet
        if not was_transmitting and self.queue:
            self._start_next()
        # If already transmitting, continue with the remaining time for the current packet
        elif was_transmitting:
            self.hold_in("TRANSMITTING", remaining)

    def lambdaf(self):
        # When the internal event triggers (transmission delay elapsed), send the packet
        if self.phase == "TRANSMITTING" and self.in_flight is not None:
            self.output["data_out"].add(dict(self.in_flight))

    def deltint(self):
        # After sending, clear the in-flight packet
        self.in_flight = None

        # If more packets are waiting, schedule the next transmission immediately
        if self.queue:
            self._start_next()
        else:
            # Otherwise, go back to idle
            self.passivate("IDLE")

    def exit(self):
        pass