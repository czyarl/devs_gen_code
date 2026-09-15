"""
Atomic DEVS model: SubnetB1

Reliable, lossless, FIFO point-to-point link with fixed one-way propagation delay.
Carries download data packets from Server boundary to Receiver.
"""

from collections import deque

from xdevs.models import Atomic, Coupled, Port


class SubnetB1(Atomic):
    """
    SubnetB1 is a reliable, lossless, FIFO point-to-point link model with a fixed
    one-way propagation delay (milliseconds of simulation time).

    Input:  data_in  (dict)  {'seq': int, 'bit': int}
    Output: data_out (dict)  {'seq': int, 'bit': int}
    """

    def __init__(self, name: str, parent: Coupled | None, delay_ms: float):
        super().__init__(name)
        self.parent = parent
        self.delay_ms = float(delay_ms)

        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "data_out"))

        # State
        self._queue: deque[dict] = deque()
        self._in_flight: dict | None = None

    def initialize(self):
        self._queue = deque()
        self._in_flight = None
        self.passivate("IDLE")

    def _start_head_timer(self) -> None:
        """Start delivery timer for the current head-of-line packet."""
        self._in_flight = self._queue[0]
        self.hold_in("DELIVER", self.delay_ms)

    def deltext(self, e: float):
        # Preserve remaining time for an already-established delivery timer.
        was_delivering = self.phase == "DELIVER"
        remaining = max(0.0, self.ta() - e) if was_delivering else None

        # Enqueue all arrivals in the order provided by the message bag iterator.
        for packet in self.input["data_in"].values:
            # Treat as opaque payload; do not modify.
            self._queue.append(packet)

        if was_delivering:
            # Do not change the already-established delivery time.
            self.hold_in("DELIVER", remaining)
        else:
            # If queue was empty before arrivals, start timer for head-of-line.
            if self._queue:
                self._start_head_timer()
            else:
                self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "DELIVER" and self._in_flight is not None:
            # Emit exactly one message equal to the head packet (unchanged).
            self.output["data_out"].add(self._in_flight)

    def deltint(self):
        if self.phase == "DELIVER":
            # Remove the delivered head-of-line packet.
            if self._queue:
                self._queue.popleft()

            self._in_flight = None

            # Schedule next delivery or become passive.
            if self._queue:
                self._start_head_timer()
            else:
                self.passivate("IDLE")
        else:
            # Defensive: any other phase becomes passive.
            self.passivate("IDLE")

    def exit(self):
        pass