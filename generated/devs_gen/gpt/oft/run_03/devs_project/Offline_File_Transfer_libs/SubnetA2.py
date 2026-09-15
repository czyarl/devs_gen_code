"""
SubnetA2: Reliable, lossless, FIFO-preserving one-way link for ACK messages.

- Transports ACKs from Server boundary back to Sender.
- Fixed propagation delay: delay_ms (simulation milliseconds).
- No external IO.
"""

from __future__ import annotations

from collections import deque

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class SubnetA2(Atomic):
    def __init__(self, name: str, parent: Coupled | None, delay_ms: float):
        super().__init__(name)
        self.parent = parent
        self.delay_ms = float(delay_ms)

        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "ack_out"))

        # FIFO of (release_time_ms, payload_dict)
        self._pending: deque[tuple[float, dict]] = deque()

        # Prepared output for the next internal event (head-of-line)
        self._to_emit: dict | None = None

    def initialize(self):
        self._pending.clear()
        self._to_emit = None
        self.passivate("IDLE")

    @staticmethod
    def _is_valid_ack(msg: object) -> bool:
        if not isinstance(msg, dict):
            return False
        if "bit" not in msg:
            return False
        bit = msg.get("bit")
        return bit in (0, 1)

    def _reschedule_from_queue(self) -> None:
        if not self._pending:
            self._to_emit = None
            self.passivate("IDLE")
            return

        now = get_current_time()
        head_release_time, head_payload = self._pending[0]
        self._to_emit = head_payload
        self.hold_in("DELIVER", max(0.0, head_release_time - now))

    def deltext(self, e: float):
        now = get_current_time()

        for msg in self.input["ack_in"].values:
            if not self._is_valid_ack(msg):
                continue
            payload = dict(msg)
            release_time_ms = now + self.delay_ms
            self._pending.append((release_time_ms, payload))

        self._reschedule_from_queue()

    def lambdaf(self):
        if self.phase != "DELIVER":
            return
        if self._to_emit is None:
            return
        self.output["ack_out"].add(dict(self._to_emit))

    def deltint(self):
        now = get_current_time()

        # Remove exactly one item (the one just emitted). It must be due now.
        if self._pending and self._pending[0][0] <= now:
            self._pending.popleft()

        self._reschedule_from_queue()

    def exit(self):
        pass