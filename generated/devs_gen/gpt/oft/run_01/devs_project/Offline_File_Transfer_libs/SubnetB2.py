from collections import deque

from xdevs.models import Atomic, Coupled, Port


class SubnetB2(Atomic):
    """
    Reliable, lossless, FIFO point-to-point link transporting Receiver->Server ACK packets
    with fixed propagation delay delay_ms (simulation time in milliseconds).
    """

    def __init__(self, name: str, parent: Coupled | None, delay_ms: float):
        super().__init__(name)
        self.parent = parent

        self.delay_ms: float = float(delay_ms)
        self.fifo: deque[dict] = deque()
        self.in_flight: dict | None = None

        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "ack_out"))

    def initialize(self):
        self.fifo = deque()
        self.in_flight = None
        self.passivate("IDLE")

    def _start_next_delivery(self) -> None:
        # Head-of-line becomes scheduled for delivery after fixed delay.
        self.in_flight = self.fifo.popleft()
        self.hold_in("DELIVER", max(0.0, self.delay_ms))

    def deltext(self, e: float):
        # Preserve already-established next delivery time if already active.
        was_delivering = self.phase == "DELIVER"
        remaining = max(0.0, self.ta() - e) if was_delivering else None

        for ack in self.input["ack_in"].values:
            # Assume/validate format {'bit': int} with bit in {0,1}; do not transform.
            self.fifo.append(ack)

        if not was_delivering:
            if self.fifo:
                self._start_next_delivery()
            else:
                self.passivate("IDLE")
        else:
            # Keep the existing schedule; new arrivals only append behind.
            self.hold_in("DELIVER", remaining)

    def lambdaf(self):
        if self.phase == "DELIVER" and self.in_flight is not None:
            self.output["ack_out"].add(self.in_flight)

    def deltint(self):
        # Completed one delivery.
        self.in_flight = None
        if self.fifo:
            self._start_next_delivery()
        else:
            self.passivate("IDLE")

    def exit(self):
        pass