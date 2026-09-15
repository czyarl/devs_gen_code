"""Complete implementation of the Employee2 Atomic DEVS model."""

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


class Employee2(Atomic):
    """Implementation of the Employee2 model."""

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
        self.output["available_out"].add({"employee_id": 2})
        print(json.dumps({
            "time": 0.0,
            "time_str": _format_time(0.0),
            "event": "employee_available",
            "entity_type": "employee",
            "entity": "Employee_2",
            "payload": {"employee_id": 2},
        }), flush=True)

    def deltext(self, e):
        if self.phase == "BUSY":
            self.continuef(e)
            return
        for job in self.input["job_in"].values:
            if self.current_job is None:
                self.current_job = dict(job)
                self.hold_in("BUSY", self.service_time_mean + 3 * self.service_time_stddev)
                return
        self.passivate("IDLE")

    def lambdaf(self):
        now = get_current_time()
        if self.phase == "BUSY" and self.current_job is not None:
            job = self.current_job
            delay = now - job["arrival_time"]
            print(json.dumps({
                "time": now,
                "time_str": _format_time(now),
                "event": "client_served",
                "entity_type": "employee",
                "entity": "Employee_2",
                "payload": {
                    "client_id": job["client_id"],
                    "employee_id": 2,
                    "arrived": job["arrival_time"],
                    "dispatched": now,
                    "delay": delay,
                }
            }), flush=True)
            self.current_job = None
            self.output["available_out"].add({"employee_id": 2})
            print(json.dumps({
                "time": now,
                "time_str": _format_time(now),
                "event": "employee_available",
                "entity_type": "employee",
                "entity": "Employee_2",
                "payload": {"employee_id": 2},
            }), flush=True)

    def deltint(self):
        self.passivate("IDLE")

    def exit(self):
        pass