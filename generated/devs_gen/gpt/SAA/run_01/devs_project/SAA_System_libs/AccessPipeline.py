from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass
from typing import Any

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


@dataclass(frozen=True)
class _ScheduledEmission:
    time: float
    kind: str  # "ALARMADMIN", "AUTH", "DISPLAY"
    port: int
    value: int


class AccessPipeline(Atomic):
    """
    Atomic DEVS model implementing the secure-area access pipeline.

    Responsibilities (per locked contract):
    - Track secure-area state ("Disarmed"/"Armed") starting at t=0.0 in "Disarmed".
    - Apply busy/ignore rule based on AlarmAdmin working window.
    - For accepted requests, schedule and emit timed pipeline outputs and stage facts.
    - For every received request (accepted or ignored), emit an operation fact immediately.
    """

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

        self.add_out_port(Port(dict, "alarmadmin_to_auth_out"))
        self.add_out_port(Port(dict, "auth_to_alarmadmin_out"))
        self.add_out_port(Port(dict, "auth_to_display_out"))
        self.add_out_port(Port(dict, "stage_event_fact_out"))
        self.add_out_port(Port(dict, "operation_fact_out"))

        # Remembered state
        self.current_state: str = "Disarmed"
        self.busy_until: float | None = None

        # Scheduling
        self._pq: list[tuple[float, int, _ScheduledEmission]] = []
        self._seq = itertools.count()

        # Output batching for current internal event time
        self._pending_outputs: dict[str, list[dict[str, Any]]] = {}

    def initialize(self):
        self.current_state = "Disarmed"
        self.busy_until = None
        self._pq = []
        self._pending_outputs = {}
        self.passivate("IDLE")

    @staticmethod
    def _msg(port: int, value: int) -> str:
        return f"{{{port} {value}}}"

    def _is_busy(self, t: float) -> bool:
        return self.busy_until is not None and t < self.busy_until

    def _schedule_emission(self, emission: _ScheduledEmission) -> None:
        heapq.heappush(self._pq, (emission.time, next(self._seq), emission))

    def _next_deadline(self) -> float | None:
        if not self._pq:
            return None
        return self._pq[0][0]

    def _reschedule_to_next_deadline(self) -> None:
        next_time = self._next_deadline()
        if next_time is None:
            self.passivate("IDLE")
            return
        now = get_current_time()
        sigma = max(0.0, float(next_time) - float(now))
        self.hold_in("EMIT", sigma)

    def deltext(self, e: float):
        # Preserve any already-scheduled internal event deadline.
        was_active = self.phase != "IDLE"
        remaining = max(0.0, self.ta() - e) if was_active else None

        now = get_current_time()

        # Process all incoming requests at this simulation time.
        for request in self.input["request_in"].values:
            t = float(request["input_time"])
            port = int(request["port"])
            value = int(request["value"])

            # Contract states inputs arrive at simulation time t == input_time.
            # We do not enforce equality strictly; we use current time for "immediate".
            accepted = not self._is_busy(now)

            action = "disarm" if value == 0 else "arm"
            completion_time = (
                now + self.alarm_admin_delay + self.authentication_delay if accepted else None
            )

            # Immediate operation fact for every received request.
            self._pending_outputs.setdefault("operation_fact_out", []).append(
                {
                    "input_time": t,
                    "action": action,
                    "completed": bool(accepted),
                    "completion_time": completion_time,
                }
            )

            if not accepted:
                continue

            t_alarmadmin = now + self.alarm_admin_delay
            t_auth = now + self.alarm_admin_delay + self.authentication_delay
            t_display = now + self.alarm_admin_delay + self.authentication_delay + self.display_delay

            # Busy until authentication completion time.
            self.busy_until = t_auth

            self._schedule_emission(
                _ScheduledEmission(time=t_alarmadmin, kind="ALARMADMIN", port=port, value=value)
            )
            self._schedule_emission(
                _ScheduledEmission(time=t_auth, kind="AUTH", port=port, value=value)
            )
            self._schedule_emission(
                _ScheduledEmission(time=t_display, kind="DISPLAY", port=port, value=value)
            )

        # If we have immediate outputs to emit, schedule a 0-delay internal event.
        if any(self._pending_outputs.values()):
            self.hold_in("EMIT", 0.0)
            return

        # Otherwise, keep prior internal schedule if any, else schedule next deadline if any.
        if was_active and remaining is not None:
            self.hold_in(self.phase, remaining)
        else:
            self._reschedule_to_next_deadline()

    def lambdaf(self):
        now = get_current_time()

        # Emit any immediate pending outputs (e.g., operation facts).
        for port_name, msgs in list(self._pending_outputs.items()):
            if not msgs:
                continue
            for msg in msgs:
                self.output[port_name].add(msg)

        # Emit all scheduled emissions due at 'now' (within exact equality).
        # Since DEVS fires internal events exactly at scheduled times, we use ==.
        while self._pq and self._pq[0][0] == now:
            _, _, emission = heapq.heappop(self._pq)
            port = emission.port
            value = emission.value
            message = self._msg(port, value)

            if emission.kind == "ALARMADMIN":
                self.output["alarmadmin_to_auth_out"].add(
                    {
                        "time": now,
                        "message": message,
                        "port": port,
                        "value": value,
                    }
                )
                self.output["stage_event_fact_out"].add(
                    {
                        "time": now,
                        "component": "alarmAdmin",
                        "message": message,
                    }
                )

            elif emission.kind == "AUTH":
                auth_state = "DisarmValid" if value == 0 else "ArmValid"
                self.output["auth_to_alarmadmin_out"].add(
                    {
                        "time": now,
                        "message": message,
                        "state": auth_state,
                        "port": port,
                        "value": value,
                    }
                )
                self.output["stage_event_fact_out"].add(
                    {
                        "time": now,
                        "component": "authentication",
                        "message": message,
                        "state": auth_state,
                    }
                )

            elif emission.kind == "DISPLAY":
                display_state = "Disarmed" if value == 0 else "Armed"
                self.output["auth_to_display_out"].add(
                    {
                        "time": now,
                        "message": message,
                        "display_state": display_state,
                        "port": port,
                        "value": value,
                    }
                )
                self.output["stage_event_fact_out"].add(
                    {
                        "time": now,
                        "component": "display",
                        "message": message,
                        "state": display_state,
                    }
                )
                # Update system state at display time.
                self.current_state = display_state

    def deltint(self):
        # Clear immediate pending outputs after they have been emitted.
        self._pending_outputs = {}

        # Schedule next internal event if more emissions remain.
        self._reschedule_to_next_deadline()

    def exit(self):
        pass