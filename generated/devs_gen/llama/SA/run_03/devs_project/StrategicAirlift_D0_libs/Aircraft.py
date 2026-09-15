"""Complete pattern: Aircraft DEVS model.

The Aircraft model simulates an aircraft's lifecycle, including
assignment, loading, flight, unloading, return, and maintenance.
"""

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json
import sys


class Aircraft(Atomic):
    """Simulate an aircraft's lifecycle."""

    def __init__(self, name: str, parent: Coupled | None, flight_time: float, unload_time: float, return_time: float, maintenance_time: float):
        super().__init__(name)
        self.parent = parent
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
        for packet in self.input["assignment"].values:
            assignment = packet
            self.assignment = assignment
            self.hold_in("LOADING", 0.0)
        return None


    def lambdaf(self):
        if self.phase == "LOADING":
            self.output["depart"].add({
                "aircraft_id": self.assignment['aircraft_id'],
                "pallet_id": self.assignment['pallet_id'],
            })
            self.hold_in("FLYING", self.flight_time)
        elif self.phase == "UNLOADING":
            self.output["return"].add({
                "aircraft_id": self.assignment['aircraft_id'],
            })
            self.hold_in("RETURNING", self.return_time)
        elif self.phase == "MAINTENANCE":
            self.output["maintenance_end"].add({
                "aircraft_id": self.assignment['aircraft_id'],
            })
            self.hold_in("IDLE", float('inf'))


    def deltint(self):
        if self.phase == "FLYING":
            self.hold_in("UNLOADING", self.unload_time)
        elif self.phase == "RETURNING":
            self.hold_in("MAINTENANCE", self.maintenance_time)
        elif self.phase == "MAINTENANCE":
            pass
        else:
            self.passivate()


    def exit(self):
        pass