import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Aircraft(Atomic):
    """Represents a single aircraft with a stable ID that cycles through idle, loading, flying, unloading, returning, and maintenance states."""

    def __init__(self, name: str, parent: Coupled | None, aircraft_id: int, flight_time: float, unload_time: float, return_time: float, maintenance_time: float):
        super().__init__(name)
        self.parent = parent
        self.aircraft_id = aircraft_id
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.add_in_port(Port(dict, "assignment_in"))
        self.add_out_port(Port(dict, "idle_out"))
        self.add_out_port(Port(dict, "delivery_out"))
        self.current_pallet = None
        self.state = "IDLE"
        self.remaining_time = 0.0

    def initialize(self):
        # Emit initial idle status
        self.output["idle_out"].add({"aircraft_id": self.aircraft_id})
        print(json.dumps({
            "time": 0.0,
            "entity": "aircraft",
            "event": "depart",
            "payload": {
                "aircraft_id": self.aircraft_id,
                "pallet_id": -1
            }
        }), flush=True)
        self.passivate("IDLE")

    def deltext(self, e):
        if self.state == "IDLE":
            # Check for assignment
            for assignment in self.input["assignment_in"].values:
                if assignment["aircraft_id"] == self.aircraft_id:
                    self.current_pallet = assignment
                    self.state = "LOADING"
                    self.remaining_time = 0.0
                    self.hold_in("LOADING", 0.0)
                    return
            self.passivate("IDLE")
        elif self.state == "LOADING":
            self.continuef(e)
        elif self.state == "FLYING":
            self.continuef(e)
        elif self.state == "UNLOADING":
            self.continuef(e)
        elif self.state == "RETURNING":
            self.continuef(e)
        elif self.state == "MAINTENANCE":
            self.continuef(e)
        else:
            self.passivate("IDLE")

    def lambdaf(self):
        now = get_current_time()
        if self.state == "LOADING":
            # Emit depart event
            self.output["idle_out"].add({"aircraft_id": self.aircraft_id})
            print(json.dumps({
                "time": now,
                "entity": "aircraft",
                "event": "depart",
                "payload": {
                    "aircraft_id": self.aircraft_id,
                    "pallet_id": self.current_pallet["pallet_id"]
                }
            }), flush=True)
            self.state = "FLYING"
            self.remaining_time = self.flight_time
            self.hold_in("FLYING", self.flight_time)
        elif self.state == "FLYING":
            # Emit return event
            print(json.dumps({
                "time": now,
                "entity": "aircraft",
                "event": "return",
                "payload": {
                    "aircraft_id": self.aircraft_id
                }
            }), flush=True)
            self.state = "UNLOADING"
            self.remaining_time = self.unload_time
            self.hold_in("UNLOADING", self.unload_time)
        elif self.state == "UNLOADING":
            # Emit delivery event
            self.output["delivery_out"].add({
                "pallet_id": self.current_pallet["pallet_id"],
                "aircraft_id": self.aircraft_id,
                "generation_time": self.current_pallet["generation_time"]
            })
            print(json.dumps({
                "time": now,
                "entity": "destination",
                "event": "pallet_delivered",
                "payload": {
                    "pallet_id": self.current_pallet["pallet_id"],
                    "aircraft_id": self.aircraft_id,
                    "latency": now - self.current_pallet["generation_time"]
                }
            }), flush=True)
            self.state = "RETURNING"
            self.remaining_time = self.return_time
            self.hold_in("RETURNING", self.return_time)
        elif self.state == "RETURNING":
            # Emit maintenance start event
            print(json.dumps({
                "time": now,
                "entity": "aircraft",
                "event": "maintenance_start",
                "payload": {
                    "aircraft_id": self.aircraft_id
                }
            }), flush=True)
            self.state = "MAINTENANCE"
            self.remaining_time = self.maintenance_time
            self.hold_in("MAINTENANCE", self.maintenance_time)
        elif self.state == "MAINTENANCE":
            # Emit maintenance end event
            print(json.dumps({
                "time": now,
                "entity": "aircraft",
                "event": "maintenance_end",
                "payload": {
                    "aircraft_id": self.aircraft_id
                }
            }), flush=True)
            self.state = "IDLE"
            self.current_pallet = None
            self.output["idle_out"].add({"aircraft_id": self.aircraft_id})
            self.passivate("IDLE")

    def deltint(self):
        if self.state == "LOADING":
            self.state = "FLYING"
            self.remaining_time = self.flight_time
            self.hold_in("FLYING", self.flight_time)
        elif self.state == "FLYING":
            self.state = "UNLOADING"
            self.remaining_time = self.unload_time
            self.hold_in("UNLOADING", self.unload_time)
        elif self.state == "UNLOADING":
            self.state = "RETURNING"
            self.remaining_time = self.return_time
            self.hold_in("RETURNING", self.return_time)
        elif self.state == "RETURNING":
            self.state = "MAINTENANCE"
            self.remaining_time = self.maintenance_time
            self.hold_in("MAINTENANCE", self.maintenance_time)
        elif self.state == "MAINTENANCE":
            self.state = "IDLE"
            self.current_pallet = None
            self.output["idle_out"].add({"aircraft_id": self.aircraft_id})
            self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass