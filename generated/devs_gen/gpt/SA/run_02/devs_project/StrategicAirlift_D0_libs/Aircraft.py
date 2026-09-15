"""Atomic DEVS Aircraft model (xdevs.py).

Implements a non-preemptive transport cycle with external JSONL logging to stdout
and DEVS port outputs for idle and delivery notifications.

Locked interface contract:
- Class: Aircraft(Atomic)
- __init__(name, parent, aircraft_id, flight_time, unload_time, return_time, maintenance_time)
- Ports:
  - in:  assignment_in: dict
  - out: idle_out: dict
  - out: delivered_out: dict
- External IO:
  - stdout JSONL events: depart, return, maintenance_start, maintenance_end
  - stderr optional warnings (non-JSONL)
"""

import json
import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class Aircraft(Atomic):
    # Phases / FSM states
    IDLE = "IDLE"
    FLYING_TO_DEST = "FLYING_TO_DEST"
    UNLOADING = "UNLOADING"
    RETURNING = "RETURNING"
    MAINTENANCE = "MAINTENANCE"

    # Output helper phases (sigma=0)
    _ANNOUNCE_IDLE = "ANNOUNCE_IDLE"
    _DEPART = "DEPART"
    _DELIVER = "DELIVER"
    _RETURN_AND_MAINT_START = "RETURN_AND_MAINT_START"
    _MAINT_END_AND_IDLE = "MAINT_END_AND_IDLE"

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        aircraft_id: int,
        flight_time: float,
        unload_time: float,
        return_time: float,
        maintenance_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        self.aircraft_id = aircraft_id
        self.flight_time = float(flight_time)
        self.unload_time = float(unload_time)
        self.return_time = float(return_time)
        self.maintenance_time = float(maintenance_time)

        self.add_in_port(Port(dict, "assignment_in"))
        self.add_out_port(Port(dict, "idle_out"))
        self.add_out_port(Port(dict, "delivered_out"))

        # Trip context (valid while busy)
        self.pallet_id: int | None = None
        self.generation_time: float | None = None

    # -------------------------
    # Helpers
    # -------------------------
    def _warn(self, msg: str) -> None:
        print(f"[Aircraft {self.aircraft_id}] {msg}", file=sys.stderr, flush=True)

    def _stdout_event(self, now: float, event: str, payload: dict) -> None:
        # Must be JSONL on stdout with exact schema from locked contract.
        print(
            json.dumps(
                {
                    "time": float(now),
                    "entity": "aircraft",
                    "event": event,
                    "payload": payload,
                }
            ),
            flush=True,
        )

    def _is_valid_assignment(self, msg: object) -> bool:
        if not isinstance(msg, dict):
            return False
        required = ("aircraft_id", "pallet_id", "generation_time")
        for k in required:
            if k not in msg:
                return False
        if not isinstance(msg["aircraft_id"], int):
            return False
        if not isinstance(msg["pallet_id"], int):
            return False
        if not isinstance(msg["generation_time"], (int, float)):
            return False
        return True

    def _nonneg(self, value: float) -> float:
        # Interpret durations as nonnegative seconds; clamp negatives to 0 with warning.
        if value < 0.0:
            self._warn(f"Configured duration {value} < 0; clamping to 0.0")
            return 0.0
        return float(value)

    # -------------------------
    # DEVS methods
    # -------------------------
    def initialize(self):
        # Ensure nonnegative durations.
        self.flight_time = self._nonneg(self.flight_time)
        self.unload_time = self._nonneg(self.unload_time)
        self.return_time = self._nonneg(self.return_time)
        self.maintenance_time = self._nonneg(self.maintenance_time)

        self.pallet_id = None
        self.generation_time = None

        # Must emit idle_out at t=0, but outputs only in lambdaf => schedule 0-delay.
        self.hold_in(self._ANNOUNCE_IDLE, 0.0)

    def deltext(self, e: float):
        # Ignore all assignments while busy (capacity=1, no preemption).
        if self.phase != self.IDLE:
            # Preserve remaining time if active; if already passivated in a non-IDLE
            # phase (shouldn't happen), keep it.
            if self.sigma != float("inf"):
                self.continuef(e)
            return

        # IDLE: accept at most one matching assignment at this simulation time.
        accepted = False
        for msg in self.input["assignment_in"].values:
            if accepted:
                continue
            if not self._is_valid_assignment(msg):
                # Ignore malformed messages; optionally warn.
                self._warn(f"Ignoring malformed assignment: {msg!r}")
                continue
            if msg["aircraft_id"] != self.aircraft_id:
                continue

            # Accept assignment
            self.pallet_id = int(msg["pallet_id"])
            self.generation_time = float(msg["generation_time"])

            # Loading is instantaneous: depart at exactly t_assign (now).
            self.hold_in(self._DEPART, 0.0)
            accepted = True

        if not accepted:
            # Remain idle, waiting for input.
            self.passivate(self.IDLE)

    def lambdaf(self):
        now = get_current_time()

        if self.phase == self._ANNOUNCE_IDLE:
            self.output["idle_out"].add({"aircraft_id": self.aircraft_id})

        elif self.phase == self._DEPART:
            # External stdout depart event at assignment acceptance time.
            if self.pallet_id is not None:
                self._stdout_event(
                    now,
                    "depart",
                    {"aircraft_id": self.aircraft_id, "pallet_id": int(self.pallet_id)},
                )
            else:
                self._warn("Depart phase reached without pallet_id; suppressing depart log")

        elif self.phase == self._DELIVER:
            # Delivery DEVS output at unload completion time.
            if self.pallet_id is not None and self.generation_time is not None:
                self.output["delivered_out"].add(
                    {
                        "aircraft_id": self.aircraft_id,
                        "pallet_id": int(self.pallet_id),
                        "generation_time": float(self.generation_time),
                    }
                )
            else:
                self._warn("Deliver phase reached without trip context; suppressing delivered_out")

        elif self.phase == self._RETURN_AND_MAINT_START:
            # Two stdout events at same simulation time, back-to-back: return then maintenance_start.
            self._stdout_event(now, "return", {"aircraft_id": self.aircraft_id})
            self._stdout_event(now, "maintenance_start", {"aircraft_id": self.aircraft_id})

        elif self.phase == self._MAINT_END_AND_IDLE:
            # maintenance_end stdout event then idle_out at same time.
            self._stdout_event(now, "maintenance_end", {"aircraft_id": self.aircraft_id})
            self.output["idle_out"].add({"aircraft_id": self.aircraft_id})

    def deltint(self):
        # Advance FSM and schedule next internal event or passivate.
        if self.phase == self._ANNOUNCE_IDLE:
            self.passivate(self.IDLE)
            return

        if self.phase == self._DEPART:
            # Immediately enter flight phase and schedule flight completion.
            self.hold_in(self.FLYING_TO_DEST, self.flight_time)
            return

        if self.phase == self.FLYING_TO_DEST:
            # Flight completed -> unloading
            self.hold_in(self.UNLOADING, self.unload_time)
            return

        if self.phase == self.UNLOADING:
            # Unload completed -> delivery moment; output must occur at this time.
            self.hold_in(self._DELIVER, 0.0)
            return

        if self.phase == self._DELIVER:
            # Clear pallet fields only after emitting delivered_out.
            self.pallet_id = None
            self.generation_time = None
            # Start return phase
            self.hold_in(self.RETURNING, self.return_time)
            return

        if self.phase == self.RETURNING:
            # Return completed -> emit return and maintenance_start at same time.
            self.hold_in(self._RETURN_AND_MAINT_START, 0.0)
            return

        if self.phase == self._RETURN_AND_MAINT_START:
            # Immediately begin maintenance at same simulation time.
            self.hold_in(self.MAINTENANCE, self.maintenance_time)
            return

        if self.phase == self.MAINTENANCE:
            # Maintenance completed -> emit maintenance_end and idle_out at same time.
            self.hold_in(self._MAINT_END_AND_IDLE, 0.0)
            return

        if self.phase == self._MAINT_END_AND_IDLE:
            # Become idle and wait for new assignment.
            self.passivate(self.IDLE)
            return

        # Fallback: if somehow in IDLE with an internal event, just passivate.
        self.passivate(self.IDLE)

    def exit(self):
        # No special termination action.
        pass