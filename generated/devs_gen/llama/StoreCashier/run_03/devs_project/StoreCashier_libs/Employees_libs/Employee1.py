"""Complete implementation of the Employee1 atomic DEVS model."""

import json
from math import normalvariate
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
    """Simulate an employee with a specified service time distribution."""

    def __init__(self, name: str, parent: Coupled | None, mean: float, stddev: float):
        super().__init__(name)
        self.parent = parent
        self.mean = mean
        self.stddev = stddev
        self.add_in_port(Port(dict, "employee_available_in"))
        self.add_out_port(Port(dict, "employee_available_out"))
        self.busy = False

    def initialize(self):
        self.busy = False
        # Initial availability is a real DEVS event, so schedule lambdaf at t=0.
        self.output["employee_available_out"].add({"employee_id": 1})
        self.passivate("AVAILABLE")

    def deltext(self, e):
        if self.phase == "BUSY":
            self.continuef(e)
            return
        for _ in self.input["employee_available_in"].values:
            self.hold_in("AVAILABLE", 0.0)
            return
        self.passivate("AVAILABLE")

    def lambdaf(self):
        if self.phase == "AVAILABLE" and not self.busy:
            self.busy = True
            service_time = self.mean if self.stddev == 0 else normalvariate(self.mean, self.stddev)
            self.hold_in("BUSY", service_time)

    def deltint(self):
        if self.phase == "BUSY":
            self.busy = False
            self.output["employee_available_out"].add({"employee_id": 1})
        self.passivate("AVAILABLE")

    def exit(self):
        pass