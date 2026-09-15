"""
Atomic DEVS model: SubnetB2

Reliable, lossless, FIFO one-way link transporting Receiver ACK messages to the
Server boundary with a fixed propagation delay (milliseconds of simulation time).
"""

from collections import deque

from xdevs.models import Atomic, Coupled, Port


class SubnetB2(Atomic):
    """
    SubnetB2 is a transparent delayed FIFO transport for ACK messages.

    - Input:  ack_in  (dict)  e.g., {'bit': 0|1} (but forwarded unchanged even if malformed)
    - Output: ack_out (dict)  forwarded exactly delay_ms after acceptance, FIFO
    """

    def __init__(self, name: str, parent: Coupled | None, delay_ms: float):
        super().__init__(name)
        self.parent = parent
        self.delay_ms = float(delay_ms)

        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "ack_out"))

        self._queue: deque[dict] = deque()
        self._in_flight: dict | None = None

    def initialize(self):
        self._queue.clear()
        self._in_flight = None
        self.passivate("IDLE")

    def _start_next_delivery(self) -> None:
        # Head-of-line becomes in-flight; schedule its delivery after delay_ms.
        self._in_flight = self._queue.popleft()
        self.hold_in("DELIVER", self.delay_ms)

    def deltext(self, e: float):
        # Confluence requirement: if an external arrives at the exact same time
        # as a scheduled internal delivery, the matured delivery must not be
        # delayed. We keep default xDEVS deltcon (deltint then deltext(0)),
        # and in deltext we must not reschedule/extend a just-matured delivery.
        was_delivering = self.phase == "DELIVER"
        remaining = max(0.0, self.ta() - e) if was_delivering else None

        for ack in self.input["ack_in"].values:
            # Transparent link: forward unchanged; do not validate/correct.
            self._queue.append(ack)

        if not was_delivering:
            if self._in_flight is None and self._queue:
                self._start_next_delivery()
        else:
            # Preserve the already scheduled delivery time for current head.
            self.hold_in("DELIVER", remaining)

    def lambdaf(self):
        if self.phase == "DELIVER" and self._in_flight is not None:
            self.output["ack_out"].add(self._in_flight)

    def deltint(self):
        # Delivery event fires: output already emitted in lambdaf().
        self._in_flight = None
        if self._queue:
            self._start_next_delivery()
        else:
            self.passivate("IDLE")

    def exit(self):
        pass