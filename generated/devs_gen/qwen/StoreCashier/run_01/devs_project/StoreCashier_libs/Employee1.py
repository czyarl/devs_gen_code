"""Employee1 model implementing the atomic DEVS specification."""

import json
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


class Employee1(Atomic):
    """Employee1 model as specified in the locked contract."""

    def __init__(self, name: str, parent: Coupled | None, employee_mean: float, employee_stddev: float):
        super().__init__(name)
        self.parent = parent
        self.employee_mean = employee_mean
        self.employee_stddev = employee_stddev
        self.add_in_port(Port(dict, "client_in"))
        self.add_out_port(Port(dict, "available_out"))
        self.is_busy = False
        self.current_client = None
        self.service_start_time = None

    def initialize(self):
        self.is_busy = False
        self.current_client = None
        self.service_start_time = None
        # Emit initial availability at t=0
        self.hold_in("ANNOUNCE_AVAILABLE", 0.0)

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return
        for client in self.input["client_in"].values:
            if not self.is_busy:
                self.is_busy = True
                self.current_client = dict(client)
                self.service_start_time = get_current_time()
                # Sample service duration within valid range
                if self.employee_stddev == 0.0:
                    service_duration = self.employee_mean
                else:
                    # Ensure duration is within bounds
                    min_duration = self.employee_mean - 3 * self.employee_stddev
                    max_duration = self.employee_mean + 3 * self.employee_stddev
                    service_duration = random.gauss(self.employee_mean, self.employee_stddev)
                    service_duration = max(min_duration, min(max_duration, service_duration))
                self.hold_in("PROCESSING", service_duration)
                return
        self.passivate("IDLE")

    def _emit_availability(self, now: float) -> None:
        # Internal communication: emit on available_out port
        self.output["available_out"].add({"employee_id": 1})

        # External observation: write JSONL record to stdout
        print(json.dumps({
            "time": now,
            "time_str": _format_time(now),
            "event": "employee_available",
            "entity_type": "employee",
            "entity": "Employee_1",
            "payload": {"employee_id": 1}
        }), flush=True)

    def _emit_client_served(self, now: float) -> None:
        # External observation: write JSONL record to stdout
        client = self.current_client
        arrived = client["arrival_time"]
        dispatched = now
        delay = dispatched - arrived
        print(json.dumps({
            "time": now,
            "time_str": _format_time(now),
            "event": "client_served",
            "entity_type": "employee",
            "entity": "Employee_1",
            "payload": {
                "client_id": client["client_id"],
                "employee_id": 1,
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
            self.is_busy = False
            self.current_client = None
            self.service_start_time = None
        self.passivate("IDLE")

    def exit(self):
        pass