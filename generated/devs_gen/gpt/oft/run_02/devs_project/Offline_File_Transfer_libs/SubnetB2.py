from collections import deque

from xdevs.models import Atomic, Coupled, Port


class SubnetB2(Atomic):
    """
    Reliable, lossless, FIFO channel transporting download-loop ACK messages
    from Receiver back to Server boundary with a fixed propagation delay.
    """

    def __init__(self, name: str, parent: Coupled | None, delay_ms: float):
        super().__init__(name)
        self.parent = parent

        # Fixed nonnegative delay in simulation milliseconds
        self.delay_ms = float(delay_ms)
        if self.delay_ms < 0.0:
            self.delay_ms = 0.0

        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "ack_out"))

        self._queue: deque[dict] = deque()
        self._in_flight: dict | None = None

    def initialize(self):
        self._queue.clear()
        self._in_flight = None
        self.passivate("IDLE")

    @staticmethod
    def _is_valid_ack(payload) -> bool:
        return (
            isinstance(payload, dict)
            and "bit" in payload
            and payload["bit"] in (0, 1)
        )

    def _start_next_delivery(self) -> None:
        # Called only when queue is non-empty and model is idle or after a delivery.
        self._in_flight = self._queue.popleft()
        self.hold_in("DELIVER", self.delay_ms)

    def deltext(self, e: float):
        # Preserve the already-scheduled head-of-line delivery time if busy.
        was_delivering = self.phase == "DELIVER"
        remaining = max(0.0, self.ta() - e) if was_delivering else None

        was_empty_before = len(self._queue) == 0 and self._in_flight is None

        for ack in self.input["ack_in"].values:
            if self._is_valid_ack(ack):
                # Preserve payload unchanged (store reference as-is).
                self._queue.append(ack)

        if was_delivering:
            # Do not change the already scheduled delivery time.
            self.hold_in("DELIVER", remaining)
        else:
            # If previously idle and now have something pending, schedule first delivery.
            if was_empty_before and self._queue:
                self._start_next_delivery()
            else:
                # Remain idle (either still empty, or should not happen since idle implies no in_flight)
                if self._in_flight is None and not self._queue:
                    self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "DELIVER" and self._in_flight is not None:
            self.output["ack_out"].add(self._in_flight)

    def deltint(self):
        # Completed one delivery
        self._in_flight = None

        if self._queue:
            # Fixed per-message delay between deliveries
            self._start_next_delivery()
        else:
            self.passivate("IDLE")

    def exit(self):
        pass