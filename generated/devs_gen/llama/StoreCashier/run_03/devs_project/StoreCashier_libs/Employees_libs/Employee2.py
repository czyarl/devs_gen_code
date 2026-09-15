"""Complete pattern: one semantic event has both DEVS and external effects."""

import json
from typing import Dict

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
    """Announce availability internally and externally at the same event time."""

    def __init__(self, name: str, parent: Coupled | None, mean: float, stddev: float):
        super().__init__(name)
        self.parent = parent
        self.mean = mean
        self.stddev = stddev
        self.add_in_port(Port(dict, "employee_available_in"))
        self.add_out_port(Port(dict, "employee_available_out"))

    def initialize(self):
        # Initial availability is a real DEVS event, so schedule lambdaf at t=0.
        self.hold_in("ANNOUNCE_AVAILABLE", 0.0)

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return
        for work in self.input["employee_available_in"].values:
            self.hold_in("PROCESSING", 0.0)
            return
        self.passivate("IDLE")

    def _emit_availability(self, now: float) -> None:
        availability = {"employee_id": 2}

        # Internal communication: another DEVS model consumes this payload.
        self.output["employee_available_out"].add(dict(availability))

        # External observation: this is an independent required side effect.
        print(json.dumps({
            "time": now,
            "time_str": _format_time(now),
            "event": "employee_available",
            "entity_type": "employee",
            # External labels come from the locked contract; they need not be
            # inferred from the Python class or instance name.
            "entity": "Employee_2",
            "payload": {"employee_id": 2},
        }), flush=True)

    def lambdaf(self):
        now = get_current_time()
        if self.phase == "ANNOUNCE_AVAILABLE":
            self._emit_availability(now)
        elif self.phase == "PROCESSING":
            # Nobody inside this example consumes completion, so completion is
            # logged but is not placed on an invented DEVS output port.
            print(json.dumps({
                "time": now,
                "time_str": _format_time(now),
                "event": "client_served",
                "entity_type": "employee",
                "entity": "Employee_2",
                "payload": {"client_id": 1, "employee_id": 2, "arrived": now, "dispatched": now, "delay": 0.0},
            }), flush=True)
            self._emit_availability(now)

    def deltint(self):
        self.passivate("IDLE")

    def exit(self):
        pass