import sys
from collections import deque

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class SubnetA1(Atomic):
    """
    Reliable, order-preserving FIFO delay channel for upload-loop data packets
    traveling from Sender to the Server boundary.

    - Time unit: milliseconds (simulation time).
    - Fixed delay: delay_ms (typically 3000.0).
    - State: unbounded FIFO of (deliver_at_ms, packet_dict).
    """

    def __init__(self, name: str, parent: Coupled | None, delay_ms: float):
        super().__init__(name)
        self.parent = parent
        self.delay_ms = float(delay_ms)

        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "data_out"))

        self._pending: deque[tuple[float, dict]] = deque()
        self._due_batch: list[dict] = []

    def initialize(self):
        self._pending = deque()
        self._due_batch = []
        self.passivate("IDLE")

    @staticmethod
    def _is_valid_packet(val) -> bool:
        if not isinstance(val, dict):
            return False
        if "seq" not in val or "bit" not in val:
            return False
        if not isinstance(val["seq"], int):
            return False
        if val["bit"] not in (0, 1):
            return False
        return True

    def _reschedule_from_pending(self) -> None:
        if not self._pending:
            self.passivate("IDLE")
            return

        now = get_current_time()
        next_time = min(deliver_at for deliver_at, _ in self._pending)
        self.hold_in("WAITING", max(0.0, next_time - now))

    def deltext(self, e: float):
        now = get_current_time()

        for msg in self.input["data_in"].values:
            if not self._is_valid_packet(msg):
                # Ignore malformed messages; optionally log to stderr.
                print(
                    f"{self.name}: ignoring malformed packet on data_in: {msg!r}",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            deliver_at = now + (self.delay_ms if self.delay_ms > 0.0 else 0.0)
            # Forward unchanged payload dict (do not modify contents).
            self._pending.append((deliver_at, msg))

        self._reschedule_from_pending()

    def lambdaf(self):
        if self.phase != "WAITING":
            return

        now = get_current_time()

        # Emit all packets due "now" in FIFO order, with timestamp now (no extra delay).
        self._due_batch = []
        for deliver_at, packet in self._pending:
            if deliver_at <= now:
                self._due_batch.append(packet)
            else:
                break

        for packet in self._due_batch:
            self.output["data_out"].add(packet)

    def deltint(self):
        now = get_current_time()

        # Remove exactly those emitted as due (deliver_at <= now), preserving FIFO.
        while self._pending and self._pending[0][0] <= now:
            self._pending.popleft()

        self._due_batch = []
        self._reschedule_from_pending()

    def exit(self):
        pass