"""
Atomic DEVS model: SubnetA1

Reliable, lossless, FIFO point-to-point link with fixed one-way propagation delay.
Carries upload data packets from data_in to data_out without modifying payload.
"""

from collections import deque

from xdevs.models import Atomic, Coupled, Port


class SubnetA1(Atomic):
    """
    SubnetA1: reliable FIFO link with fixed delay (ms).

    - Input:  data_in  (dict) payload {'seq': int, 'bit': int}
    - Output: data_out (dict) payload {'seq': int, 'bit': int}

    Timing semantics:
    - When idle and a packet arrives at time t, it is scheduled for delivery at t + delay_ms.
    - When backlogged, exactly one packet is delivered per internal event, spaced by delay_ms.
    - delay_ms == 0 is supported via successive zero-delay internal events.
    """

    def __init__(self, name: str, parent: Coupled | None, delay_ms: float):
        super().__init__(name)
        self.parent = parent
        self.delay_ms = float(delay_ms)

        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "data_out"))

        self._queue: deque[dict] = deque()
        self._in_flight: dict | None = None

    def initialize(self):
        self._queue = deque()
        self._in_flight = None
        self.passivate("IDLE")

    def _start_head_service(self) -> None:
        """Move head-of-line packet into in-flight and schedule its delivery."""
        self._in_flight = self._queue.popleft()
        self.hold_in("DELIVER", self.delay_ms)

    def deltext(self, e: float):
        # Preserve remaining time for an already scheduled delivery.
        was_delivering = self.phase == "DELIVER"
        remaining = max(0.0, self.ta() - e) if was_delivering else None

        # Enqueue all arrivals in the order presented by the simulator.
        for pkt in self.input["data_in"].values:
            # Do not modify payload fields; store as-is (but ensure independent dict object).
            self._queue.append(dict(pkt))

        # If idle before arrivals and now non-empty, schedule delivery for new head.
        if not was_delivering and self._in_flight is None and self._queue:
            self._start_head_service()
        elif was_delivering:
            # Additional arrivals do not change the currently scheduled delivery time.
            self.hold_in("DELIVER", remaining)

    def lambdaf(self):
        if self.phase == "DELIVER" and self._in_flight is not None:
            self.output["data_out"].add(self._in_flight)

    def deltint(self):
        # Completed a delivery event; clear in-flight and schedule next if queued.
        self._in_flight = None
        if self._queue:
            self._start_head_service()
        else:
            self.passivate("IDLE")

    def exit(self):
        # No external I/O and no special termination action.
        pass