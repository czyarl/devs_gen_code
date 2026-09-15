from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


@dataclass
class _ScheduledEmission:
    due_time: float
    kind: str  # "admin" | "auth" | "display"
    port: int
    value: int
    message: str
    input_time: float


class AccessPipeline(Atomic):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        alarm_admin_delay: float,
        authentication_delay: float,
        display_delay: float,
    ):
        super().__init__(name)
        self.parent = parent

        self.alarm_admin_delay = float(alarm_admin_delay)
        self.authentication_delay = float(authentication_delay)
        self.display_delay = float(display_delay)

        self.add_in_port(Port(dict, "request_in"))
        self.add_in_port(Port(dict, "auth_result_in"))

        self.add_out_port(Port(dict, "to_auth_out"))
        self.add_out_port(Port(dict, "auth_result_out"))
        self.add_out_port(Port(dict, "to_display_out"))
        self.add_out_port(Port(dict, "stage_event_fact_out"))
        self.add_out_port(Port(dict, "operation_fact_out"))

        # State
        self.system_state: str = "Disarmed"
        self.busy_until: float | None = None

        # Time-ordered schedule of pending emissions
        self._schedule: list[_ScheduledEmission] = []

        # Prepared batch for the next internal firing
        self._pending_outputs: dict[str, list[dict[str, Any]]] = {}

    def initialize(self):
        self.system_state = "Disarmed"
        self.busy_until = None
        self._schedule = []
        self._pending_outputs = {}
        self.passivate("IDLE")

    # ---------- Helpers ----------
    def _action_from_value(self, value: int) -> str:
        return "disarm" if int(value) == 0 else "arm"

    def _auth_state_from_value(self, value: int) -> str:
        return "DisarmValid" if int(value) == 0 else "ArmValid"

    def _display_state_from_value(self, value: int) -> str:
        return "Disarmed" if int(value) == 0 else "Armed"

    def _insert_scheduled(self, item: _ScheduledEmission) -> None:
        # Keep schedule sorted by due_time; stable insertion.
        idx = 0
        while idx < len(self._schedule) and self._schedule[idx].due_time <= item.due_time:
            idx += 1
        self._schedule.insert(idx, item)

    def _recompute_next_internal(self) -> None:
        if not self._schedule:
            self.passivate("IDLE")
            return
        now = get_current_time()
        next_time = self._schedule[0].due_time
        sigma = max(0.0, float(next_time - now))
        self.hold_in("EMIT", sigma)

    def _prepare_outputs_for_time(self, fire_time: float) -> None:
        self._pending_outputs = {
            "to_auth_out": [],
            "auth_result_out": [],
            "to_display_out": [],
            "stage_event_fact_out": [],
            "operation_fact_out": [],
        }

        # Pop all items due now (exact time match)
        due: list[_ScheduledEmission] = []
        while self._schedule and self._schedule[0].due_time == fire_time:
            due.append(self._schedule.pop(0))

        for item in due:
            if item.kind == "admin":
                self._pending_outputs["to_auth_out"].append(
                    {
                        "time": fire_time,
                        "port": item.port,
                        "value": item.value,
                        "message": item.message,
                    }
                )
                self._pending_outputs["stage_event_fact_out"].append(
                    {
                        "time": fire_time,
                        "component": "alarmAdmin",
                        "message": item.message,
                    }
                )
            elif item.kind == "auth":
                auth_state = self._auth_state_from_value(item.value)
                self._pending_outputs["auth_result_out"].append(
                    {
                        "time": fire_time,
                        "port": item.port,
                        "value": item.value,
                        "message": item.message,
                        "auth_state": auth_state,
                    }
                )
                self._pending_outputs["stage_event_fact_out"].append(
                    {
                        "time": fire_time,
                        "component": "authentication",
                        "message": item.message,
                        "state": auth_state,
                    }
                )
            elif item.kind == "display":
                display_state = self._display_state_from_value(item.value)
                self._pending_outputs["to_display_out"].append(
                    {
                        "time": fire_time,
                        "port": item.port,
                        "value": item.value,
                        "message": item.message,
                        "display_state": display_state,
                    }
                )
                self._pending_outputs["stage_event_fact_out"].append(
                    {
                        "time": fire_time,
                        "component": "display",
                        "message": item.message,
                        "state": display_state,
                    }
                )

    def _process_auth_completion(self, msg: dict) -> None:
        # Mark AlarmAdmin as no longer busy for times >= t_auth.
        t_auth = float(msg["time"])
        if self.busy_until is not None and t_auth >= self.busy_until:
            self.busy_until = None

        # Update system_state deterministically based on value.
        value = int(msg["value"])
        if value == 0:
            self.system_state = "Disarmed"
        else:
            self.system_state = "Armed"

    def _accept_request(self, req: dict) -> None:
        t = float(req["input_time"])
        port = int(req["port"])
        value = int(req["value"])
        message = str(req["message"])

        t_admin = t + self.alarm_admin_delay
        t_auth = t + self.alarm_admin_delay + self.authentication_delay
        t_disp = t + self.alarm_admin_delay + self.authentication_delay + self.display_delay

        self.busy_until = t_auth

        # Exactly one operation fact per request_in
        self._pending_outputs["operation_fact_out"].append(
            {
                "input_time": t,
                "action": self._action_from_value(value),
                "completed": True,
                "completion_time": t_auth,
            }
        )

        # Schedule stage emissions and pipeline messages
        self._insert_scheduled(
            _ScheduledEmission(
                due_time=t_admin,
                kind="admin",
                port=port,
                value=value,
                message=message,
                input_time=t,
            )
        )
        self._insert_scheduled(
            _ScheduledEmission(
                due_time=t_auth,
                kind="auth",
                port=port,
                value=value,
                message=message,
                input_time=t,
            )
        )
        self._insert_scheduled(
            _ScheduledEmission(
                due_time=t_disp,
                kind="display",
                port=port,
                value=value,
                message=message,
                input_time=t,
            )
        )

    def _ignore_request(self, req: dict) -> None:
        t = float(req["input_time"])
        value = int(req["value"])
        self._pending_outputs["operation_fact_out"].append(
            {
                "input_time": t,
                "action": self._action_from_value(value),
                "completed": False,
                "completion_time": None,
            }
        )

    # ---------- DEVS transitions ----------
    def deltext(self, e: float):
        # Preserve remaining time if we were already scheduled.
        was_active = self.phase != "IDLE"
        remaining = max(0.0, self.ta() - e) if was_active else None

        # Collect incoming messages
        auth_msgs = [dict(m) for m in self.input["auth_result_in"].values]
        req_msgs = [dict(m) for m in self.input["request_in"].values]

        # Clear any previously prepared outputs; external events may cause immediate output.
        self._pending_outputs = {
            "to_auth_out": [],
            "auth_result_out": [],
            "to_display_out": [],
            "stage_event_fact_out": [],
            "operation_fact_out": [],
        }

        # Concurrency rule: if auth_result_in and request_in at same time,
        # treat as not busy for the request. Process auth completions first.
        for msg in auth_msgs:
            self._process_auth_completion(msg)

        now = get_current_time()

        # Process all requests; acceptance is evaluated after auth completions at same time.
        for req in req_msgs:
            t = float(req["input_time"])
            # Busy rule: busy if busy_until is not None and t < busy_until
            busy = self.busy_until is not None and t < self.busy_until
            if busy:
                self._ignore_request(req)
            else:
                self._accept_request(req)

        # If we produced any immediate outputs (operation facts), schedule immediate firing.
        if self._pending_outputs["operation_fact_out"]:
            self.hold_in("EMIT_IMMEDIATE", 0.0)
            return

        # Otherwise, keep existing schedule timing or (if idle) schedule next.
        if was_active and remaining is not None:
            # Keep the earlier internal event deadline.
            self.hold_in(self.phase, remaining)
        else:
            self._recompute_next_internal()

    def lambdaf(self):
        now = get_current_time()

        if self.phase == "EMIT":
            # Prepare outputs for this scheduled time and emit them.
            self._prepare_outputs_for_time(now)

        # Emit whatever is prepared for this firing (immediate or scheduled).
        for payload in self._pending_outputs.get("to_auth_out", []):
            self.output["to_auth_out"].add(payload)
        for payload in self._pending_outputs.get("auth_result_out", []):
            self.output["auth_result_out"].add(payload)
        for payload in self._pending_outputs.get("to_display_out", []):
            self.output["to_display_out"].add(payload)
        for payload in self._pending_outputs.get("stage_event_fact_out", []):
            self.output["stage_event_fact_out"].add(payload)
        for payload in self._pending_outputs.get("operation_fact_out", []):
            self.output["operation_fact_out"].add(payload)

    def deltint(self):
        # Clear prepared outputs after firing.
        self._pending_outputs = {
            "to_auth_out": [],
            "auth_result_out": [],
            "to_display_out": [],
            "stage_event_fact_out": [],
            "operation_fact_out": [],
        }
        self._recompute_next_internal()

    def exit(self):
        pass