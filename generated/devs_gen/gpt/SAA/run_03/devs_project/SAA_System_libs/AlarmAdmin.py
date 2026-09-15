from __future__ import annotations

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class AlarmAdmin(Atomic):
    def __init__(self, name: str, parent: Coupled | None, alarm_admin_delay: float = 10.0):
        super().__init__(name)
        self.parent = parent
        self.alarm_admin_delay = float(alarm_admin_delay)

        # Inputs
        self.add_in_port(Port(dict, "request_in"))
        self.add_in_port(Port(dict, "auth_complete_in"))

        # Outputs
        self.add_out_port(Port(dict, "to_auth_out"))
        self.add_out_port(Port(dict, "alarmadmin_event_out"))
        self.add_out_port(Port(dict, "operation_fact_out"))
        self.add_out_port(Port(dict, "operation_update_out"))

        # State (initialized in initialize())
        self.busy: bool = False
        self.inflight_request: dict | None = None
        self.pending_forward: bool = False
        self.forward_time: float = 0.0

        # Output buffers (set before an internal event; emitted in lambdaf)
        self._pending_operation_facts: list[dict] = []
        self._pending_operation_updates: list[dict] = []
        self._emit_forward_outputs: bool = False

    def initialize(self):
        self.busy = False
        self.inflight_request = None
        self.pending_forward = False
        self.forward_time = 0.0

        self._pending_operation_facts = []
        self._pending_operation_updates = []
        self._emit_forward_outputs = False

        self.passivate("IDLE")

    @staticmethod
    def _action_from_value(value: int) -> str:
        return "disarm" if int(value) == 0 else "arm"

    def _schedule_next(self):
        """Schedule next internal event based on pending outputs and forward timer."""
        now = float(get_current_time())

        # Priority: immediate output buffers (facts/updates) should be emitted ASAP.
        if self._pending_operation_facts or self._pending_operation_updates:
            self.hold_in("EMIT_IMMEDIATE", 0.0)
            return

        # Next: scheduled forwarding event
        if self.pending_forward:
            sigma = max(0.0, float(self.forward_time) - now)
            self.hold_in("FORWARD", sigma)
            return

        self.passivate("IDLE")

    def deltext(self, e: float):
        # If we were already scheduled for an internal event, preserve remaining time.
        if self.phase != "IDLE":
            self.continuef(e)

        # Confluence requirement: if auth_complete_in and request_in arrive at same time,
        # process completion first, then requests.
        completions = list(self.input["auth_complete_in"].values)
        requests = list(self.input["request_in"].values)

        # Process completions first
        for payload in completions:
            # Defensive: always emit update; clear busy/inflight if it was active.
            update = {
                "input_time": payload.get("input_time"),
                "completion_time": payload.get("completion_time"),
            }
            self._pending_operation_updates.append(update)

            # Clear busy state (even if mismatch/idle; do not crash)
            self.busy = False
            self.inflight_request = None
            # Note: pending_forward should normally already be False by completion time.
            # If it isn't (unexpected), we leave it as-is; the contract only requires
            # not crashing and allowing collector to decide.

        # Process requests
        for req in requests:
            # Always emit exactly one operation_fact_out per request at arrival time.
            action = self._action_from_value(req.get("value", 0))
            accepted = not self.busy

            fact = {
                "input_time": req.get("input_time"),
                "action": action,
                "completed": bool(accepted),
                "completion_time": None,
            }
            self._pending_operation_facts.append(fact)

            if accepted:
                # Accept and schedule forwarding after alarm_admin_delay
                now = float(get_current_time())
                self.busy = True
                self.inflight_request = dict(req)
                self.pending_forward = True
                self.forward_time = now + float(self.alarm_admin_delay)
            else:
                # Ignore: no further outputs for this request
                pass

        # Decide what internal event happens next.
        self._schedule_next()

    def lambdaf(self):
        # Emit immediate operation facts/updates (same simulation time as arrival)
        if self.phase == "EMIT_IMMEDIATE":
            for fact in self._pending_operation_facts:
                self.output["operation_fact_out"].add(dict(fact))
            for upd in self._pending_operation_updates:
                self.output["operation_update_out"].add(dict(upd))
            return

        # Emit forwarding outputs at forward_time
        if self.phase == "FORWARD":
            if self.pending_forward and self.inflight_request is not None:
                self.output["to_auth_out"].add(dict(self.inflight_request))
                self.output["alarmadmin_event_out"].add(
                    {
                        "time": float(get_current_time()),
                        "component": "alarmAdmin",
                        "message": self.inflight_request.get("message"),
                    }
                )

    def deltint(self):
        if self.phase == "EMIT_IMMEDIATE":
            self._pending_operation_facts.clear()
            self._pending_operation_updates.clear()
            self._schedule_next()
            return

        if self.phase == "FORWARD":
            # Forwarding done; remain busy until completion arrives.
            self.pending_forward = False
            self._emit_forward_outputs = False
            self._schedule_next()
            return

        # Fallback: no internal work
        self._schedule_next()

    def exit(self):
        pass