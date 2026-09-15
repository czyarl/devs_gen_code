"""Atomic DEVS model: Employee.

Implements one cashier employee that alternates between IDLE and BUSY, announces
availability (stdout JSONL + DEVS output) at t=0.0 and after each completion,
and logs service completion (stdout JSONL) when service finishes within horizon.
"""

import json
import math
import random

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


def _format_time(value: float) -> str:
    """Format simulation seconds as HH:MM:SS:mmm."""
    total_milliseconds = int(round(value * 1000))
    total_seconds, milliseconds = divmod(total_milliseconds, 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"


def _derive_employee_seed(seed: int, employee_id: int) -> int:
    """Derive a deterministic per-employee seed from a shared seed."""
    # Simple deterministic mixing (no external deps).
    mixed = (seed ^ (employee_id * 0x9E3779B1)) & 0xFFFFFFFF
    mixed ^= (mixed << 13) & 0xFFFFFFFF
    mixed ^= (mixed >> 17) & 0xFFFFFFFF
    mixed ^= (mixed << 5) & 0xFFFFFFFF
    return mixed & 0xFFFFFFFF


class Employee(Atomic):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        employee_id: int,
        service_mean: float,
        service_stddev: float,
        seed: int,
    ):
        super().__init__(name)
        self.parent = parent

        self.employee_id = int(employee_id)
        self.service_mean = float(service_mean)
        self.service_stddev = float(service_stddev)
        self.seed = seed

        # Ports (locked contract)
        self.add_in_port(Port(dict, "assignment_in"))
        self.add_out_port(Port(dict, "available_out"))

        # RNG (distinct stream per employee when seed provided)
        if self.seed is None:
            self._rng = random.Random()
        else:
            self._rng = random.Random(_derive_employee_seed(int(self.seed), self.employee_id))

        # Dynamic state
        self.mode: str = "IDLE"  # IDLE | BUSY

        self.current_client_id: int | None = None
        self.current_arrival_time: float | None = None
        self.current_paired_time: float | None = None
        self.current_duration: float | None = None
        self.completion_time: float | None = None

        # Internal bookkeeping for outputs at internal events
        self._pending_outputs: list[tuple[str, dict]] = []
        self._pending_time: float | None = None

    def initialize(self):
        # Startup: employee is IDLE and must announce availability exactly once at t=0.0
        self.mode = "IDLE"
        self.current_client_id = None
        self.current_arrival_time = None
        self.current_paired_time = None
        self.current_duration = None
        self.completion_time = None

        self._pending_outputs = [("employee_available", {"employee_id": self.employee_id})]
        self._pending_time = 0.0
        self.hold_in("OUTPUT", 0.0)

    def _emit_stdout(self, event_time: float, event: str, payload: dict) -> None:
        print(
            json.dumps(
                {
                    "time": float(event_time),
                    "time_str": _format_time(float(event_time)),
                    "event": event,
                    "entity_type": "employee",
                    "entity": self.name,
                    "payload": payload,
                }
            ),
            flush=True,
        )

    def _sample_service_duration(self) -> float:
        if self.service_stddev == 0.0:
            d = float(self.service_mean)
            return 0.0 if d < 0.0 else d

        lower = self.service_mean - 3.0 * self.service_stddev
        upper = self.service_mean + 3.0 * self.service_stddev

        # Physical clamp: duration must be nonnegative.
        effective_lower = max(0.0, lower)

        # Sample from normal and reject until within bounds (bounded sampling).
        # Also handle degenerate/invalid bound ordering robustly.
        if upper < effective_lower:
            # If bounds are inconsistent after physical clamp, choose the only feasible value.
            return float(effective_lower)

        for _ in range(10000):
            d = self._rng.gauss(self.service_mean, self.service_stddev)
            if d < 0.0:
                continue
            if effective_lower <= d <= upper:
                return float(d)

        # Fallback: clamp a final draw into bounds.
        d = self._rng.gauss(self.service_mean, self.service_stddev)
        if d < 0.0:
            d = 0.0
        if d < effective_lower:
            d = effective_lower
        if d > upper:
            d = upper
        return float(d)

    def deltext(self, e: float):
        now = get_current_time()

        # Preserve remaining time if already scheduled.
        if self.phase != "passive":
            self.continuef(e)

        # Ignore assignments at/after horizon (treated as now >= horizon).
        # Horizon is runner-enforced; we cannot query it here. We implement the
        # "ignore at/after horizon" rule by being stable and producing no output;
        # suppression of after-horizon completion is handled by runner (no call)
        # or by downstream checks. If messages arrive anyway, we still accept only
        # when IDLE and schedule completion; if runner ends earlier, lambdaf won't run.
        for msg in self.input["assignment_in"].values:
            if not isinstance(msg, dict):
                continue

            # Address filtering
            if msg.get("employee_id") != self.employee_id:
                continue

            # Busy/idle rule
            if self.mode != "IDLE":
                continue

            # Accept assignment
            client_id = msg.get("client_id")
            arrival_time = msg.get("arrival_time")
            paired_time = msg.get("paired_time")

            if client_id is None or arrival_time is None or paired_time is None:
                continue

            self.current_client_id = int(client_id)
            self.current_arrival_time = float(arrival_time)
            self.current_paired_time = float(paired_time)

            d = self._sample_service_duration()
            self.current_duration = float(d)
            self.completion_time = float(now + d)

            self.mode = "BUSY"
            self._pending_outputs = []
            self._pending_time = None
            self.hold_in("BUSY", float(d))
            return

        # If nothing else to do and no internal event is scheduled, remain idle.
        if self.phase == "passive":
            self.passivate("IDLE")

    def lambdaf(self):
        now = get_current_time()

        if self.phase == "OUTPUT":
            # Emit all pending outputs at the scheduled time.
            event_time = 0.0 if self._pending_time is None else float(self._pending_time)
            for event, payload in self._pending_outputs:
                if event == "employee_available":
                    # DEVS output
                    self.output["available_out"].add({"employee_id": self.employee_id})
                    # stdout JSONL
                    self._emit_stdout(event_time, "employee_available", {"employee_id": self.employee_id})
                elif event == "client_served":
                    self._emit_stdout(event_time, "client_served", dict(payload))
            return

        if self.phase == "BUSY":
            # Service completion: log client_served then announce availability again.
            if (
                self.current_client_id is None
                or self.current_arrival_time is None
                or self.completion_time is None
            ):
                return

            dispatched = float(now)
            arrived = float(self.current_arrival_time)
            delay = float(dispatched - arrived)

            self._emit_stdout(
                dispatched,
                "client_served",
                {
                    "client_id": int(self.current_client_id),
                    "employee_id": int(self.employee_id),
                    "arrived": arrived,
                    "dispatched": dispatched,
                    "delay": delay,
                },
            )

            # Availability at the same simulation time
            self.output["available_out"].add({"employee_id": self.employee_id})
            self._emit_stdout(dispatched, "employee_available", {"employee_id": self.employee_id})

    def deltint(self):
        if self.phase == "OUTPUT":
            self._pending_outputs = []
            self._pending_time = None
            self.passivate("IDLE")
            return

        if self.phase == "BUSY":
            # Clear current client and return to IDLE; availability already emitted in lambdaf.
            self.mode = "IDLE"
            self.current_client_id = None
            self.current_arrival_time = None
            self.current_paired_time = None
            self.current_duration = None
            self.completion_time = None
            self.passivate("IDLE")
            return

        self.passivate("IDLE")

    def exit(self):
        pass