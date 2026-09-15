"""Complete pattern: one semantic event has both DEVS and external effects."""

import json
import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class Aircraft(Atomic):
    """Aircraft performs a cyclic operation: waits idle, loads assigned cargo, flies to destination, unloads cargo, returns to facility, and undergoes maintenance."""

    def __init__(self, name: str, parent: Coupled | None, flight_time: float, unload_time: float, return_time: float, maintenance_time: float):
        super().__init__(name)
        self.parent = parent
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.add_in_port(Port(dict, "assignment_arrived"))
        self.add_out_port(Port(dict, "depart"))
        self.add_out_port(Port(dict, "pallet_delivered"))
        self.assignment = None

    def initialize(self):
        self.assignment = None
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "IDLE":
            for assignment in self.input["assignment_arrived"].values:
                self.assignment = assignment
                self.hold_in("LOADING", 0.0)
                return
        self.passivate(self.phase)

    def lambdaf(self):
        now = get_current_time()
        if self.phase == "IDLE":
            pass
        elif self.phase == "LOADING":
            # Send depart event
            self.output["depart"].add({"aircraft_id": self.name, "pallet_id": self.assignment["pallet_id"]})
            self.hold_in("FLYING", self.flight_time)
        elif self.phase == "FLYING":
            self.hold_in("UNLOADING", self.unload_time)
        elif self.phase == "UNLOADING":
            # Send pallet_delivered event
            self.output["pallet_delivered"].add({"pallet_id": self.assignment["pallet_id"], "aircraft_id": self.name, "latency": get_current_time() - self.assignment["generation_time"]})
            self.hold_in("RETURNING", self.return_time)
        elif self.phase == "RETURNING":
            self.hold_in("MAINTENANCE", self.maintenance_time)
        elif self.phase == "MAINTENANCE":
            self.passivate("IDLE")

    def deltint(self):
        self.passivate("IDLE")

    def exit(self):
        pass

def main():
    print(json.dumps({"time": 0.0, "entity": "Aircraft", "event": "initialized", "payload": {}}, ), flush=True)
if __name__ == "__main__":
    main()