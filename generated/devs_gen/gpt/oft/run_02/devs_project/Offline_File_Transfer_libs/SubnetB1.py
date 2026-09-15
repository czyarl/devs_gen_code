"""SubnetB1: reliable, lossless, FIFO-preserving channel with fixed propagation delay (ms)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


@dataclass(frozen=True)
class _PendingEntry:
    delivery_time: float  # absolute simulation time in ms
    payload: dict         # {'seq': int, 'bit': 0|1}


class SubnetB1(Atomic):
    """
    Reliable FIFO channel with fixed delay_ms.

    - Accepts packets on data_in.
    - Emits the same packets unchanged on data_out exactly delay_ms later.
    - Preserves FIFO order, including for same-timestamp arrivals.
    - Buffers without loss.
    """

    def __init__(self, name: str, parent: Coupled | None, delay_ms: float):
        super().__init__(name)
        self.parent = parent
        self.delay_ms = float(delay_ms)

        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "data_out"))

        self._queue: deque[_PendingEntry] = deque()
        self._to_emit: dict | None = None

    def initialize(self):
        self._queue.clear()
        self._to_emit = None
        self.passivate("IDLE")

    @staticmethod
    def _is_valid_packet(msg) -> bool:
        if not isinstance(msg, dict):
            return False
        if "seq" not in msg or "bit" not in msg:
            return False
        return True

    def _reschedule_from_head(self) -> None:
        if not self._queue:
            self.passivate("IDLE")
            return
        now = get_current_time()
        head_time = self._queue[0].delivery_time
        self.hold_in("WAITING", max(0.0, head_time - now))

    def deltext(self, e: float):
        # Enqueue all arrivals in the order seen in the message bag iterator.
        now = get_current_time()

        was_empty = (len(self._queue) == 0)
        for msg in self.input["data_in"].values:
            if not self._is_valid_packet(msg):
                continue
            payload = msg  # do not modify; forward unchanged
            self._queue.append(_PendingEntry(now + self.delay_ms, payload))

        # If we were already active, keep the existing schedule unless we were idle.
        # However, if we were idle and got new packets, schedule from head.
        if was_empty and self._queue:
            self._reschedule_from_head()
        else:
            # Preserve remaining time if still active; if idle and still empty, remain idle.
            if self.phase != "IDLE":
                self.hold_in(self.phase, max(0.0, self.ta() - e))

    def lambdaf(self):
        if self.phase != "WAITING":
            return
        if self._to_emit is not None:
            self.output["data_out"].add(self._to_emit)

    def deltint(self):
        now = get_current_time()

        # Deliver exactly one packet per internal event: the head-of-line.
        self._to_emit = None
        if self._queue and self._queue[0].delivery_time <= now:
            entry = self._queue.popleft()
            self._to_emit = entry.payload

        # Schedule next internal event based on new head (may be due now => sigma 0).
        self._reschedule_from_head()

    def exit(self):
        pass