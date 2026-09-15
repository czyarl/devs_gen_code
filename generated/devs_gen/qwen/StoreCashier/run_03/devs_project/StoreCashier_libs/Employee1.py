"""Employee1 model implementation following the locked contract."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


def _format_time(value: float) -> str:
    """Format simulation seconds into HH:MM:SS:mmm string."""
    total_milliseconds = int(round(value * 1000))
    total_seconds, milliseconds = divmod(total_milliseconds, 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"


class Employee1(Atomic):
    """Employee1 model as specified in the locked contract."""

    def __init__(self, name: str, parent: Coupled | None, service_mean: float, service_stddev: float):
        super().__init__(name)
        self.parent = parent
        self.service_mean = service_mean
        self.service_stddev = service_stddev
        self.add_in_port(Port(dict, "client_in"))
        self.add_out_port(Port(dict, "available_out"))
        self.current_client = None
        self.is_busy = False

    def initialize(self):
        self.current_client = None
        self.is_busy = False
        # Emit initial availability at t=0
        self.hold_in("ANNOUNCE_AVAILABLE", 0.0)

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return
        for client in self.input["client_in"].values:
            if self.current_client is None and not self.is_busy:
                self.current_client = dict(client)
                self.is_busy = True
                self.hold_in("PROCESSING", self.service_mean)
                return
        self.passivate("IDLE")

    def _emit_availability(self, now: float) -> None:
        # Internal communication: notify FIFOQueue
        availability = {"employee_id": 1}
        self.output["available_out"].add(availability)

        # External observation: write to stdout
        print(json.dumps({
            "time": now,
            "time_str": _format_time(now),
            "event": "employee_available",
            "entity_type": "employee",
            "entity": "Employee_1",
            "payload": {"employee_id": 1},
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
            "entity": "Employee_1",
            "payload": {
                "client_id": client["client_id"],
                "employee_id": 1,
                "arrived": arrived,
                "dispatched": dispatched,
                "delay": delay,
            },
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
            self.is_busy = False
        self.passivate("IDLE")

    def exit(self):
        pass