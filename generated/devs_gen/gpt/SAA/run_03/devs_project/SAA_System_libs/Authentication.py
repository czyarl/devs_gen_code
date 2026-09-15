"""Atomic DEVS model: Authentication.

Deterministically authenticates (always succeeds) each accepted request received
from AlarmAdmin, and after a fixed simulation-time delay emits:
- completion feedback to AlarmAdmin,
- validation to Display,
- authentication event fact to ReportCollector.

No external I/O.
"""

from __future__ import annotations

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Authentication(Atomic):
    def __init__(self, name: str, parent: Coupled | None, authentication_delay: float = 2.0):
        super().__init__(name)
        self.parent = parent
        self.authentication_delay = float(authentication_delay)

        self.add_in_port(Port(dict, "request_in"))

        self.add_out_port(Port(dict, "complete_to_admin_out"))
        self.add_out_port(Port(dict, "validation_to_display_out"))
        self.add_out_port(Port(dict, "authentication_event_out"))

        # List of (t_auth, request_dict). Multiple overlapping requests supported.
        self._pending: list[tuple[float, dict]] = []

    def initialize(self):
        self._pending = []
        self.passivate("IDLE")

    @staticmethod
    def _auth_state_from_value(value: int) -> str:
        # Deterministic mapping; any nonzero maps to ArmValid.
        return "DisarmValid" if value == 0 else "ArmValid"

    def _reschedule_from_pending(self) -> None:
        if not self._pending:
            self.passivate("IDLE")
            return
        now = get_current_time()
        next_time = min(t_auth for t_auth, _ in self._pending)
        self.hold_in("WAITING", max(0.0, next_time - now))

    def deltext(self, e: float):
        now = get_current_time()

        # Accept every request and schedule its authentication time based on receipt time.
        for msg in self.input["request_in"].values:
            req = dict(msg)
            t_auth = now + self.authentication_delay
            self._pending.append((t_auth, req))

        # Ensure the next due item is scheduled.
        self._reschedule_from_pending()

    def lambdaf(self):
        if self.phase != "WAITING":
            return

        now = get_current_time()

        # Emit outputs for all requests due at this time (or earlier, defensively).
        for t_auth, req in self._pending:
            if t_auth <= now:
                input_time = float(req["input_time"])
                port = int(req["port"])
                value = int(req["value"])
                message = req["message"]  # preserve exactly as received (R022)

                auth_state = self._auth_state_from_value(value)

                self.output["complete_to_admin_out"].add({
                    "input_time": input_time,
                    "port": port,
                    "value": value,
                    "message": message,
                    "completion_time": float(t_auth),
                })
                self.output["validation_to_display_out"].add({
                    "input_time": input_time,
                    "port": port,
                    "value": value,
                    "message": message,
                    "auth_state": auth_state,
                })
                self.output["authentication_event_out"].add({
                    "time": float(t_auth),
                    "component": "authentication",
                    "message": message,
                    "state": auth_state,
                })

    def deltint(self):
        now = get_current_time()
        # Remove all delivered items.
        self._pending = [(t_auth, req) for (t_auth, req) in self._pending if t_auth > now]
        self._reschedule_from_pending()

    def exit(self):
        pass