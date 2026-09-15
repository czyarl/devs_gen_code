"""Complete implementation of the Employee1 atomic model."""

import json

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


def _format_time(value: float) -> str:
    """Format simulation seconds without depending on wall-clock datetime APIs."""
    total_milliseconds = int(round(value * 1000))
    total_seconds, milliseconds = divmod(total_milliseconds, 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"


class Employee1(Atomic):
    """Simulate an employee who processes one job at a time."""

    def __init__(self, name: str, parent: Coupled | None, service_time_mean: float, service_time_stddev: float):
        super().__init__(name)
        self.parent = parent
        self.service_time_mean = service_time_mean
        self.service_time_stddev = service_time_stddev
        self.add_in_port(Port(dict, "job_in"))
        self.add_out_port(Port(dict, "available_out"))
        self.current_job = None

    def initialize(self):
        self.current_job = None
        # Initial availability is a real DEVS event, so schedule lambdaf at t=0.
        self.hold_in("ANNOUNCE_AVAILABLE", 0.0)

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return
        for job in self.input["job_in"].values:
            if self.current_job is None:
                self.current_job = dict(job)
                self.hold_in("PROCESSING", self.service_time_mean)
                return
        self.passivate("IDLE")

    def _emit_availability(self, now: float) -> None:
        availability = {"employee_id": 1}

        # Internal communication: another DEVS model consumes this payload.
        self.output["available_out"].add(dict(availability))

        # External observation: this is an independent required side effect.
        print(json.dumps({
            "time": now,
            "time_str": _format_time(now),
            "event": "employee_available",
            "entity_type": "employee",
            "entity": "Employee_1",
            "payload": {"employee_id": 1},
        }), flush=True)

    def lambdaf(self):
        now = get_current_time()
        if self.phase == "ANNOUNCE_AVAILABLE":
            self._emit_availability(now)
        elif self.phase == "PROCESSING" and self.current_job is not None:
            # Log client served event
            print(json.dumps({
                "time": now,
                "time_str": _format_time(now),
                "event": "client_served",
                "entity_type": "employee",
                "entity": "Employee_1",
                "payload": {
                    "client_id": self.current_job["client_id"],
                    "employee_id": 1,
                    "arrived": self.current_job["arrival_time"],
                    "dispatched": now,
                    "delay": now - self.current_job["arrival_time"],
                },
            }), flush=True)
            self._emit_availability(now)

    def deltint(self):
        if self.phase == "PROCESSING":
            self.current_job = None
        self.passivate("IDLE")

    def exit(self):
        pass