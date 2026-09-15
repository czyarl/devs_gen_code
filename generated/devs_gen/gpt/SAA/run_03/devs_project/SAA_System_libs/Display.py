"""Atomic DEVS model: Display.

Maintains a visible system state ("Armed"/"Disarmed") and, for every incoming
validation, schedules a display emission after a fixed deterministic delay.
"""

from __future__ import annotations

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Display(Atomic):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        display_delay: float = 3.0,
        initial_state: str = "Disarmed",
    ):
        super().__init__(name)
        self.parent = parent
        self.display_delay = float(display_delay)
        self.initial_state = initial_state

        self.add_in_port(Port(dict, "validation_in"))
        self.add_out_port(Port(dict, "display_event_out"))
        self.add_out_port(Port(dict, "state_update_out"))

        # Retained visible state
        self.visible_state: str = self.initial_state

        # Pending emissions: list of tuples (t_emit: float, seq: int, message: str, state: str)
        # seq preserves arrival order for same t_emit.
        self._pending: list[tuple[float, int, str, str]] = []
        self._seq: int = 0

    def initialize(self):
        self.visible_state = self.initial_state
        self._pending = []
        self._seq = 0
        self.passivate("IDLE")

    @staticmethod
    def _value_to_state(value: int) -> str:
        # Requirements define 0->Disarmed, 1->Armed; for other values behavior is undefined.
        # We conservatively map any non-0 to "Armed" to avoid dropping emissions.
        return "Disarmed" if value == 0 else "Armed"

    def _reschedule_from_pending(self) -> None:
        if not self._pending:
            self.passivate("IDLE")
            return
        now = get_current_time()
        next_time = min(t_emit for (t_emit, _, _, _) in self._pending)
        self.hold_in("WAITING", max(0.0, next_time - now))

    def deltext(self, e: float):
        now = get_current_time()

        for validation in self.input["validation_in"].values:
            payload = dict(validation)
            value = payload.get("value")
            message = payload.get("message")

            target_state = self._value_to_state(value)
            t_emit = now + self.display_delay

            self._pending.append((t_emit, self._seq, message, target_state))
            self._seq += 1

        self._reschedule_from_pending()

    def lambdaf(self):
        if self.phase != "WAITING":
            return

        now = get_current_time()

        due = [(t_emit, seq, message, state) for (t_emit, seq, message, state) in self._pending if t_emit <= now]
        if not due:
            return

        # Emit in nondecreasing (t_emit, seq) order.
        due.sort(key=lambda x: (x[0], x[1]))

        for t_emit, _, message, state in due:
            # Update visible state for each emission (even if unchanged).
            self.visible_state = state

            self.output["display_event_out"].add(
                {
                    "time": t_emit,
                    "component": "display",
                    "message": message,
                    "state": state,
                }
            )
            self.output["state_update_out"].add(
                {
                    "time": t_emit,
                    "state": state,
                }
            )

    def deltint(self):
        now = get_current_time()
        self._pending = [(t_emit, seq, message, state) for (t_emit, seq, message, state) in self._pending if t_emit > now]
        self._reschedule_from_pending()

    def exit(self):
        pass