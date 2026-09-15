"""Complete pattern: one semantic event has both DEVS and external effects."""

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
    """Employee 1 serves clients with a fixed service time."""

    def __init__(self, name: str, parent: Coupled | None, service_time: float):
        super().__init__(name)
        self.parent = parent
        self.service_time = service_time
        self.add_in_port(Port(dict, "client_in"))
        self.add_out_port(Port(dict, "available_out"))
        self.current_client = None

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
                self.hold_in("PROCESSING", self.service_time)
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
            # External labels come from the locked contract; they need not be
            # inferred from the Python class or instance name.
            "entity": "Employee_1",
            "payload": {"employee_id": 1},
        }), flush=True)

    def lambdaf(self):
        now = get_current_time()
        if self.phase == "ANNOUNCE_AVAILABLE":
            self._emit_availability(now)
        elif self.phase == "PROCESSING" and self.current_client is not None:
            # Nobody inside this example consumes completion, so completion is
            # logged but is not placed on an invented DEVS output port.
            client = self.current_client
            print(json.dumps({
                "time": now,
                "time_str": _format_time(now),
                "event": "client_served",
                "entity_type": "employee",
                "entity": "Employee_1",
                "payload": {
                    "client_id": client["client_id"],
                    "employee_id": 1,
                    "arrived": client["arrival_time"],
                    "dispatched": now,
                    "delay": now - client["arrival_time"],
                },
            }), flush=True)
            self._emit_availability(now)

    def deltint(self):
        if self.phase == "PROCESSING":
            self.current_client = None
        self.passivate("IDLE")

    def exit(self):
        pass