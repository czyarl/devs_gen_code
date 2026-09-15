from collections import deque

from xdevs.models import Atomic, Coupled, Port


class SubnetA2(Atomic):
    """
    Reliable, lossless, FIFO channel for upload-loop ACKs (Server -> Sender)
    with a fixed propagation delay in milliseconds.
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

    def _start_head_of_line(self) -> None:
        """Move the head-of-line item into service and schedule its release."""
        self._in_flight = self._queue.popleft()
        self.hold_in("RELEASING", self.delay_ms)

    def deltext(self, e: float):
        # Preserve FIFO semantics at same-time internal/external events by
        # keeping default deltcon behavior and not preempting an in-flight item.
        was_releasing = self.phase == "RELEASING"
        remaining = max(0.0, self.ta() - e) if was_releasing else None

        for ack in self.input["ack_in"].values:
            # Accept without transformation; only ensure we store a dict snapshot.
            self._queue.append(dict(ack))

        if not was_releasing and self._in_flight is None and self._queue:
            self._start_head_of_line()
        elif was_releasing:
            # Do not alter the already scheduled release time for the current HOL.
            self.hold_in("RELEASING", remaining)

    def lambdaf(self):
        if self.phase == "RELEASING" and self._in_flight is not None:
            self.output["ack_out"].add(dict(self._in_flight))

    def deltint(self):
        # Release completed; remove emitted item and schedule next if any.
        self._in_flight = None
        if self._queue:
            self._start_head_of_line()
        else:
            self.passivate("IDLE")

    def exit(self):
        pass