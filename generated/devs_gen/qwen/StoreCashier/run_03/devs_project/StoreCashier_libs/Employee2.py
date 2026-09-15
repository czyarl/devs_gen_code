"""Complete pattern: one semantic event has both DEVS and external effects."""

import json
import math
import numpy as np

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
    """Employee 2 model with variable service duration based on normal distribution."""

    def __init__(self, name: str, parent: Coupled | None, service_mean: float, service_stddev: float):
        super().__init__(name)
        self.parent = parent
        self.service_mean = service_mean
        self.service_stddev = service_stddev
        self.add_in_port(Port(dict, "client_in"))
        self.add_out_port(Port(dict, "available_out"))
        self.current_client = None
        self.service_duration = 0.0

    def initialize(self):
        self.current_client = None
        # Initial availability is a real DEVS event, so schedule lambdaf at t=0.
        self.hold_in("ANNOUNCE_AVAILABLE", 0.0)

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return
        for client in self.input["client_in"].values:
            if self.current_client is None:
                self.current_client = dict(client)
                # Compute service duration with clipping
                if self.service_stddev == 0.0:
                    self.service_duration = self.service_mean
                else:
                    # Sample from normal distribution and clip to 3 standard deviations
                    raw_duration = np.random.normal(self.service_mean, self.service_stddev)
                    lower_bound = self.service_mean - 3 * self.service_stddev
                    upper_bound = self.service_mean + 3 * self.service_stddev
                    self.service_duration = max(lower_bound, min(upper_bound, raw_duration))
                self.hold_in("PROCESSING", self.service_duration)
                return
        self.passivate("IDLE")

    def _emit_availability(self, now: float) -> None:
        availability = {"employee_id": 2}

        # Internal communication: another DEVS model consumes this payload.
        self.output["available_out"].add(dict(availability))

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
        elif self.phase == "PROCESSING" and self.current_client is not None:
            # Emit client_served event to stdout
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
                },
            }), flush=True)
            self._emit_availability(now)

    def deltint(self):
        if self.phase == "PROCESSING":
            self.current_client = None
        self.passivate("IDLE")

    def exit(self):
        pass