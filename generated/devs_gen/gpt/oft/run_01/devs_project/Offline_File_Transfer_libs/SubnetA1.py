from collections import deque

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class SubnetA1(Atomic):
    """
    Reliable, lossless, FIFO-preserving unidirectional link:
    Sender -> Server boundary, with fixed propagation delay (ms).

    Packet format: {'seq': int, 'bit': int}
    """

    def __init__(self, name: str, parent: Coupled | None, delay_ms: float):
        super().__init__(name)
        self.parent = parent
        self.delay_ms = delay_ms

        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "data_out"))

        # Each entry: (delivery_time_ms: float, packet: dict)
        self._queue: deque[tuple[float, dict]] = deque()

        # Prepared output for the next lambdaf()
        self._to_send: dict | None = None

    def initialize(self):
        self._queue.clear()
        self._to_send = None
        self.passivate("IDLE")

    @staticmethod
    def _is_valid_packet(msg) -> bool:
        return isinstance(msg, dict) and ("seq" in msg) and ("bit" in msg)

    def _reschedule_from_head(self) -> None:
        if not self._queue:
            self.passivate("IDLE")
            return
        now = get_current_time()
        head_time, _ = self._queue[0]
        self.hold_in("WAITING", max(0.0, head_time - now))

    def deltext(self, e: float):
        was_empty = (len(self._queue) == 0)
        now = get_current_time()

        for msg in self.input["data_in"].values:
            if not self._is_valid_packet(msg):
                continue
            # Preserve payload unchanged (but copy to avoid external mutation).
            packet = dict(msg)
            self._queue.append((now + self.delay_ms, packet))

        # Scheduling rule: only (re)schedule when previously idle; otherwise
        # existing earliest deadline cannot be preempted by new arrivals.
        if was_empty and self._queue:
            self._reschedule_from_head()
        else:
            # If we were already active, preserve remaining time.
            if self.phase != "IDLE":
                self.continuef(e)

    def lambdaf(self):
        if self.phase != "WAITING":
            return

        now = get_current_time()
        if not self._queue:
            return

        delivery_time, packet = self._queue[0]
        if delivery_time <= now:
            # Emit exactly one packet per internal event.
            self._to_send = packet
            self.output["data_out"].add(dict(self._to_send))

    def deltint(self):
        now = get_current_time()

        # Remove exactly one due packet (the one emitted in lambdaf()).
        if self._queue:
            delivery_time, _ = self._queue[0]
            if delivery_time <= now:
                self._queue.popleft()

        self._to_send = None

        if not self._queue:
            self.passivate("IDLE")
            return

        next_time, _ = self._queue[0]
        if next_time <= now:
            # More packets due now: schedule immediate internal events, FIFO.
            self.hold_in("WAITING", 0.0)
        else:
            self.hold_in("WAITING", next_time - now)

    def exit(self):
        pass