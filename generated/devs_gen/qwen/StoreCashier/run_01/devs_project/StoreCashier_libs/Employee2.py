"""Complete implementation of Employee2 atomic DEVS model."""

import json
import math
import random

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
    """Employee2 atomic DEVS model for the cashier system."""

    def __init__(self, name: str, parent: Coupled | None, employee_mean: float, employee_stddev: float):
        super().__init__(name)
        self.parent = parent
        self.employee_mean = employee_mean
        self.employee_stddev = employee_stddev
        self.add_in_port(Port(dict, "client_in"))
        self.add_out_port(Port(dict, "available_out"))
        self.current_client = None
        self.is_idle = True

    def initialize(self):
        # Initial availability at t=0
        self.is_idle = True
        self.hold_in("ANNOUNCE_AVAILABLE", 0.0)

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return
        for client in self.input["client_in"].values:
            if self.current_client is None:
                self.current_client = dict(client)
                # Sample service time from normal distribution, clipped to [mean - 3*stddev, mean + 3*stddev]
                service_time = random.normalvariate(self.employee_mean, self.employee_stddev)
                min_service = self.employee_mean - 3 * self.employee_stddev
                max_service = self.employee_mean + 3 * self.employee_stddev
                service_time = max(min_service, min(max_service, service_time))
                self.hold_in("PROCESSING", service_time)
                return
        self.passivate("IDLE")

    def _emit_availability(self, now: float) -> None:
        # Internal communication: notify FIFOQueue that Employee2 can accept one client.
        self.output["available_out"].add({"employee_id": 2})

        # External observation: write to stdout
        print(json.dumps({
            "time": now,
            "time_str": _format_time(now),
            "event": "employee_available",
            "entity_type": "employee",
            "entity": "Employee_2",
            "payload": {"employee_id": 2}
        }), flush=True)

    def _emit_client_served(self, now: float) -> None:
        # External observation: write to stdout
        client = self.current_client
        dispatched = now
        arrived = client["arrival_time"]
        delay = dispatched - arrived
        print(json.dumps({
            "time": now,
            "time_str": _format_time(now),
            "event": "client_served",
            "entity_type": "employee",
            "entity": "Employee_2",
            "payload": {
                "client_id": client["client_id"],
                "employee_id": 2,
                "arrived": arrived,
                "dispatched": dispatched,
                "delay": delay
            }
        }), flush=True)

    def lambdaf(self):
        now = get_current_time()
        if self.phase == "ANNOUNCE_AVAILABLE":
            self._emit_availability(now)
        elif self.phase == "PROCESSING" and self.current_client is not None:
            self._emit_client_served(now)
            self._emit_availability(now)

    def deltint(self):
        if self.phase == "PROCESSING":
            self.current_client = None
        self.passivate("IDLE")

    def exit(self):
        pass