"""
SubnetA2: reliable, lossless, in-order (FIFO) unidirectional link for ACK packets
from Server boundary back to Sender with a fixed propagation delay (milliseconds).
"""

from collections import deque

from xdevs.models import Atomic, Coupled, Port


class SubnetA2(Atomic):
    def __init__(self, name: str, parent: Coupled | None, delay_ms: float):
        super().__init__(name)
        self.parent = parent
        self.delay_ms = float(delay_ms)

        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "ack_out"))

        self._queue: deque[dict] = deque()
        self._in_flight: dict | None = None

    def initialize(self):
        self._queue = deque()
        self._in_flight = None
        self.passivate("IDLE")

    def _start_next(self) -> None:
        self._in_flight = self._queue.popleft()
        self.hold_in("DELAYING", self.delay_ms)

    @staticmethod
    def _should_ignore(msg) -> bool:
        # Minimal validation per contract: may ignore non-dicts or dicts with invalid 'bit'.
        # Preferred robustness: forward opaque dicts unchanged; if 'bit' exists, it should be int 0/1.
        if not isinstance(msg, dict):
            return True
        if "bit" in msg:
            b = msg.get("bit")
            if not isinstance(b, int) or b not in (0, 1):
                return True
        return False

    def deltext(self, e: float):
        was_delaying = self.phase == "DELAYING"
        remaining = max(0.0, self.ta() - e) if was_delaying else None

        for ack in self.input["ack_in"].values:
            if self._should_ignore(ack):
                continue
            # Forward unchanged; keep a shallow copy to avoid accidental external mutation.
            self._queue.append(dict(ack))

        if not was_delaying and self._queue:
            self._start_next()
        elif was_delaying:
            # Preserve the already scheduled head delivery time.
            self.hold_in("DELAYING", remaining)

    def lambdaf(self):
        if self.phase == "DELAYING" and self._in_flight is not None:
            self.output["ack_out"].add(dict(self._in_flight))

    def deltint(self):
        self._in_flight = None
        if self._queue:
            # Under backlog, space deliveries by delay_ms after each delivery time.
            self._start_next()
        else:
            self.passivate("IDLE")

    def exit(self):
        pass