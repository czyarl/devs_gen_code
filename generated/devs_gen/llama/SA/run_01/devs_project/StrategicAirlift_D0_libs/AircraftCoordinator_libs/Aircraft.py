import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time

class Aircraft(Atomic):
    def __init__(self, name: str, parent: Coupled | None, aircraft_id: int, flight_time: float, unload_time: float, return_time: float, maintenance_time: float):
        super().__init__(name)
        self.parent = parent
        self.aircraft_id = aircraft_id
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.add_in_port(Port(dict, "assignment"))
        self.add_out_port(Port(dict, "depart"))
        self.add_out_port(Port(dict, "return"))
        self.add_out_port(Port(dict, "maintenance_start"))
        self.add_out_port(Port(dict, "maintenance_end"))

    def initialize(self):
        self.hold_in("IDLE", 0.0)

    def deltext(self, e):
        if self.phase == "IDLE":
            for assignment in self.input["assignment"].values:
                self.hold_in("PROCESSING", 0.0)
                return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "IDLE":
            return
        elif self.phase == "PROCESSING":
            assignment = self.input["assignment"].get()
            self.output["depart"].add({
                "aircraft_id": self.aircraft_id,
                "pallet_id": assignment["pallet_id"]
            })
            self.hold_in("FLYING", self.flight_time)
        elif self.phase == "FLYING":
            self.output["return"].add({
                "aircraft_id": self.aircraft_id
            })
            self.hold_in("UNLOADING", self.unload_time)
        elif self.phase == "UNLOADING":
            self.hold_in("RETURNING", self.return_time)
        elif self.phase == "RETURNING":
            self.output["maintenance_start"].add({
                "aircraft_id": self.aircraft_id
            })
            self.hold_in("MAINTENANCE", self.maintenance_time)
        elif self.phase == "MAINTENANCE":
            self.output["maintenance_end"].add({
                "aircraft_id": self.aircraft_id
            })
            self.passivate("IDLE")

    def deltint(self):
        self.passivate("IDLE")

    def exit(self):
        pass