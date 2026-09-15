"""Atomic DEVS model: Employee (StoreCashier.Employee)

Implements one cashier employee that can serve at most one client at a time.
Emits DEVS availability messages and writes required JSONL logs to stdout.
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


class Employee(Atomic):
    """One employee that announces availability and serves assigned clients."""

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
        self.entity = f"Employee_{self.employee_id}"

        self.service_mean = float(service_mean)
        self.service_stddev = float(service_stddev)
        self.seed = seed

        self.add_in_port(Port(dict, "assignment_in"))
        self.add_out_port(Port(dict, "available_out"))

        # State
        self.busy: bool = False
        self.current_assignment: dict | None = None

        # One-shot availability announcement indicator
        self.pending_availability_announcement: bool = False

        # Prepared outputs/logs for lambdaf
        self._emit_available_out: dict | None = None
        self._log_records: list[dict] = []

        # RNG (only used when service_stddev > 0.0)
        self._rng = random.Random(seed) if self.service_stddev > 0.0 else None

    def initialize(self):
        self.busy = False
        self.current_assignment = None

        self.pending_availability_announcement = True

        self._emit_available_out = None
        self._log_records = []

        # Initial availability at t=0.0 must be a real DEVS output event.
        self.hold_in("ANNOUNCE_AVAILABLE", 0.0)

    def _log_employee_available(self, now: float) -> None:
        print(
            json.dumps(
                {
                    "time": now,
                    "time_str": _format_time(now),
                    "event": "employee_available",
                    "entity_type": "employee",
                    "entity": self.entity,
                    "payload": {"employee_id": self.employee_id},
                }
            ),
            flush=True,
        )

    def _log_client_served(self, now: float, assignment: dict) -> None:
        arrived = float(assignment["arrival_time"])
        dispatched = float(now)
        delay = dispatched - arrived
        print(
            json.dumps(
                {
                    "time": dispatched,
                    "time_str": _format_time(dispatched),
                    "event": "client_served",
                    "entity_type": "employee",
                    "entity": self.entity,
                    "payload": {
                        "client_id": int(assignment["client_id"]),
                        "employee_id": self.employee_id,
                        "arrived": arrived,
                        "dispatched": dispatched,
                        "delay": delay,
                    },
                }
            ),
            flush=True,
        )

    def _prepare_availability_outputs(self) -> None:
        """Prepare both DEVS output and stdout record for availability."""
        now = get_current_time()
        self._emit_available_out = {"employee_id": self.employee_id}
        self._log_records.append(
            {
                "time": now,
                "time_str": _format_time(now),
                "event": "employee_available",
                "entity_type": "employee",
                "entity": self.entity,
                "payload": {"employee_id": self.employee_id},
            }
        )

    def _prepare_completion_outputs(self) -> None:
        """Prepare stdout records for completion then availability (same time)."""
        now = get_current_time()
        assignment = self.current_assignment
        if assignment is None:
            return

        arrived = float(assignment["arrival_time"])
        dispatched = float(now)
        delay = dispatched - arrived

        # Ordering constraint: client_served before employee_available at same time.
        self._log_records.append(
            {
                "time": dispatched,
                "time_str": _format_time(dispatched),
                "event": "client_served",
                "entity_type": "employee",
                "entity": self.entity,
                "payload": {
                    "client_id": int(assignment["client_id"]),
                    "employee_id": self.employee_id,
                    "arrived": arrived,
                    "dispatched": dispatched,
                    "delay": delay,
                },
            }
        )

        self._emit_available_out = {"employee_id": self.employee_id}
        self._log_records.append(
            {
                "time": dispatched,
                "time_str": _format_time(dispatched),
                "event": "employee_available",
                "entity_type": "employee",
                "entity": self.entity,
                "payload": {"employee_id": self.employee_id},
            }
        )

    def _valid_assignment(self, msg: object) -> dict | None:
        if not isinstance(msg, dict):
            return None
        required = ("client_id", "arrival_time", "employee_id", "paired_time")
        for k in required:
            if k not in msg:
                return None
        try:
            cid = int(msg["client_id"])
            eid = int(msg["employee_id"])
            at = float(msg["arrival_time"])
            pt = float(msg["paired_time"])
        except (TypeError, ValueError):
            return None
        return {"client_id": cid, "employee_id": eid, "arrival_time": at, "paired_time": pt}

    def _select_service_duration(self) -> float:
        if self.service_stddev == 0.0:
            return float(self.service_mean)

        mean = float(self.service_mean)
        std = float(self.service_stddev)
        lo = mean - 3.0 * std
        hi = mean + 3.0 * std

        # Resample until in-range (bounded-normal constraint).
        # (Alternative clamping would also satisfy the constraint, but resampling
        # better preserves the intended distribution.)
        assert self._rng is not None
        for _ in range(10000):
            d = self._rng.gauss(mean, std)
            if lo <= d <= hi:
                return float(d)
        # Fallback: clamp if numerical issues prevent acceptance.
        d = self._rng.gauss(mean, std)
        return float(min(hi, max(lo, d)))

    def deltext(self, e: float):
        # Preserve remaining time if busy.
        if self.phase in ("SERVICE", "COMPLETE_AND_ANNOUNCE"):
            self.continuef(e)

        for raw in self.input["assignment_in"].values:
            msg = self._valid_assignment(raw)
            if msg is None:
                continue
            if msg["employee_id"] != self.employee_id:
                continue
            if self.busy:
                # Ignore when already busy.
                continue

            # Accept assignment immediately.
            self.busy = True
            self.current_assignment = msg
            self.pending_availability_announcement = False

            d = self._select_service_duration()

            # Schedule completion.
            self.hold_in("SERVICE", max(0.0, float(d)))
            return

        # If nothing accepted and no internal event pending, remain/passivate.
        if self.phase not in ("SERVICE", "COMPLETE_AND_ANNOUNCE", "ANNOUNCE_AVAILABLE"):
            self.passivate("IDLE")

    def lambdaf(self):
        now = get_current_time()

        if self.phase == "ANNOUNCE_AVAILABLE":
            # Emit DEVS availability and log at t=0.0 (and any other time this phase is used).
            self.output["available_out"].add({"employee_id": self.employee_id})
            self._log_employee_available(now)
            return

        if self.phase == "COMPLETE_AND_ANNOUNCE":
            # Emit completion log then availability log; also emit DEVS availability.
            if self.current_assignment is not None:
                self._log_client_served(now, self.current_assignment)
            self.output["available_out"].add({"employee_id": self.employee_id})
            self._log_employee_available(now)
            return

        # No other phases produce output.

    def deltint(self):
        if self.phase == "ANNOUNCE_AVAILABLE":
            self.pending_availability_announcement = False
            self.passivate("IDLE")
            return

        if self.phase == "SERVICE":
            # Service completes now; schedule immediate output phase.
            self.hold_in("COMPLETE_AND_ANNOUNCE", 0.0)
            return

        if self.phase == "COMPLETE_AND_ANNOUNCE":
            # After output, become idle.
            self.busy = False
            self.current_assignment = None
            self.pending_availability_announcement = False
            self.passivate("IDLE")
            return

        self.passivate("IDLE")

    def exit(self):
        pass