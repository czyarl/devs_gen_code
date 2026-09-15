import sys
import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Aircraft(Atomic):
    PHASE_OUTPUT_READY = "OUTPUT_READY"
    PHASE_IDLE = "IDLE"
    PHASE_FLYING = "FlyingToDestination"
    PHASE_UNLOADING = "Unloading"
    PHASE_RETURNING = "Returning"
    PHASE_MAINTENANCE = "Maintenance"

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

        self.aircraft_id = int(aircraft_id)
        self.flight_time = float(flight_time)
        self.unload_time = float(unload_time)
        self.return_time = float(return_time)
        self.maintenance_time = float(maintenance_time)

        self.add_in_port(Port(dict, "assignment_in"))
        self.add_out_port(Port(dict, "idle_out"))
        self.add_out_port(Port(dict, "delivery_out"))

        # Busy context (retained across phases until maintenance end)
        self.pallet_id: int | None = None
        self.generation_time: float | None = None

        # Pending DEVS outputs (emitted only in lambdaf when phase==OUTPUT_READY)
        self._pending_idle: dict | None = None
        self._pending_delivery: dict | None = None

        # Pending stdout JSONL records to emit at OUTPUT_READY
        self._pending_stdout_records: list[dict] = []

    def _emit_stdout_record(self, record: dict) -> None:
        # Must not emit any non-JSONL text to stdout.
        print(json.dumps(record), flush=True)

    def _prepare_idle_out(self) -> None:
        self._pending_idle = {"aircraft_id": self.aircraft_id}

    def _prepare_delivery_out(self) -> None:
        # Delivery message includes retained generation_time for latency computation downstream.
        if self.pallet_id is None or self.generation_time is None:
            # Should not happen; keep silent on stdout, optional warning to stderr.
            print(
                f"Warning: Aircraft {self.aircraft_id} attempted delivery without pallet context.",
                file=sys.stderr,
                flush=True,
            )
            return
        self._pending_delivery = {
            "aircraft_id": self.aircraft_id,
            "pallet_id": self.pallet_id,
            "generation_time": float(self.generation_time),
        }

    def _queue_aircraft_event(self, time_value: float, event: str, payload: dict) -> None:
        self._pending_stdout_records.append(
            {"time": float(time_value), "entity": "aircraft", "event": event, "payload": dict(payload)}
        )

    def initialize(self):
        # Autonomously enter idle and schedule an idle_out message at t=0.
        self.pallet_id = None
        self.generation_time = None
        self._pending_idle = None
        self._pending_delivery = None
        self._pending_stdout_records = []

        self._prepare_idle_out()
        self.hold_in(self.PHASE_OUTPUT_READY, 0.0)

    def deltext(self, e: float):
        # No preemption: ignore addressed assignments while busy.
        if self.phase != self.PHASE_IDLE:
            self.continuef(e)
            return

        accepted = False
        for msg in self.input["assignment_in"].values:
            if not isinstance(msg, dict):
                continue
            if msg.get("aircraft_id") != self.aircraft_id:
                continue
            if accepted:
                continue

            # Accept only if currently idle.
            accepted = True
            self.pallet_id = int(msg["pallet_id"])
            self.generation_time = float(msg["generation_time"])

            t_assign = get_current_time()

            # Emit required stdout JSONL depart record at assignment time (load is 0.0).
            self._queue_aircraft_event(
                t_assign,
                "depart",
                {"aircraft_id": self.aircraft_id, "pallet_id": self.pallet_id},
            )

            # Begin timed cycle immediately: flying for flight_time.
            self.hold_in(self.PHASE_FLYING, self.flight_time)
            return

        # Remain idle; preserve that we are waiting for assignments.
        self.passivate(self.PHASE_IDLE)

    def lambdaf(self):
        if self.phase != self.PHASE_OUTPUT_READY:
            return

        # DEVS outputs
        if self._pending_idle is not None:
            self.output["idle_out"].add(dict(self._pending_idle))
        if self._pending_delivery is not None:
            self.output["delivery_out"].add(dict(self._pending_delivery))

        # External IO: stdout JSONL records
        for rec in self._pending_stdout_records:
            self._emit_stdout_record(rec)

    def deltint(self):
        if self.phase == self.PHASE_FLYING:
            # Start unloading immediately after flight completes.
            self.hold_in(self.PHASE_UNLOADING, self.unload_time)

        elif self.phase == self.PHASE_UNLOADING:
            # Delivery moment is exactly at unload completion.
            self._pending_idle = None
            self._pending_delivery = None
            self._pending_stdout_records = []
            self._prepare_delivery_out()
            # Emit delivery_out at this same simulation time.
            self.hold_in(self.PHASE_OUTPUT_READY, 0.0)

        elif self.phase == self.PHASE_RETURNING:
            # At return completion: emit return and maintenance_start stdout records.
            t_return = get_current_time()
            self._pending_idle = None
            self._pending_delivery = None
            self._pending_stdout_records = []
            self._queue_aircraft_event(t_return, "return", {"aircraft_id": self.aircraft_id})
            self._queue_aircraft_event(t_return, "maintenance_start", {"aircraft_id": self.aircraft_id})
            self.hold_in(self.PHASE_OUTPUT_READY, 0.0)

        elif self.phase == self.PHASE_MAINTENANCE:
            # At maintenance completion: emit maintenance_end stdout and idle_out.
            t_end = get_current_time()
            self._pending_idle = None
            self._pending_delivery = None
            self._pending_stdout_records = []
            self._queue_aircraft_event(t_end, "maintenance_end", {"aircraft_id": self.aircraft_id})
            self._prepare_idle_out()
            self.hold_in(self.PHASE_OUTPUT_READY, 0.0)

        elif self.phase == self.PHASE_OUTPUT_READY:
            # Decide what the OUTPUT_READY was for, then advance.
            if self._pending_delivery is not None:
                # After delivery output, proceed to Returning.
                self._pending_delivery = None
                self._pending_idle = None
                self._pending_stdout_records = []
                self.hold_in(self.PHASE_RETURNING, self.return_time)

            elif self._pending_idle is not None:
                # Idle output can happen at initialization or after maintenance_end.
                # If we are coming from maintenance completion, clear pallet context.
                # (At initialization, context is already None.)
                self.pallet_id = None
                self.generation_time = None

                self._pending_idle = None
                self._pending_delivery = None
                self._pending_stdout_records = []
                self.passivate(self.PHASE_IDLE)

            elif self._pending_stdout_records:
                # This OUTPUT_READY was for stdout-only events (return + maintenance_start).
                self._pending_stdout_records = []
                self.hold_in(self.PHASE_MAINTENANCE, self.maintenance_time)

            else:
                # Nothing pending; default to idle.
                self.passivate(self.PHASE_IDLE)

        else:
            # Any unexpected phase: go idle.
            self.passivate(self.PHASE_IDLE)

    def exit(self):
        # No special end-of-simulation action required.
        pass