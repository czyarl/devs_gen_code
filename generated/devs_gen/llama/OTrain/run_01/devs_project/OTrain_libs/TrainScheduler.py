"""Train Scheduler model.

This atomic model controls the movement of the single train across the network.
It generates a `train_arrival` event at every stop.
"""

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json
import sys


class TrainScheduler(Atomic):
    """Train Scheduler model."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "train_arrival"))

    def initialize(self):
        self.stations = [
            {"id": 1, "name": "Bayview"},
            {"id": 2, "name": "Carling"},
            {"id": 3, "name": "Carleton"},
            {"id": 4, "name": "Confed"},
            {"id": 5, "name": "Greenboro"},
        ]
        self.directions = [0, 1]
        self.route_sequence = [
            (1, 0), (2, 0), (3, 0), (4, 0), (5, 1), (4, 1), (3, 1), (2, 1), (1, 0)
        ]
        self.current_station_index = 0
        self.current_direction = 0
        self.train_arrival_time = 0.0
        self.print_train_arrival()

    def deltext(self, e):
        pass

    def lambdaf(self):
        pass

    def deltint(self):
        self.train_arrival_time += 225
        self.print_train_arrival()
        self.hold_in("WAIT", 225)

    def exit(self):
        pass

    def print_train_arrival(self):
        station = next((s for s in self.stations if s["id"] == self.route_sequence[self.current_station_index][0]), None)
        event = {
            "time": self.train_arrival_time,
            "event": "train_arrival",
            "entity_type": "train",
            "station_id": station["id"],
            "station": station["name"],
            "payload": {
                "station_id": station["id"],
                "station": station["name"],
                "direction": self.route_sequence[self.current_station_index][1]
            }
        }
        print(json.dumps(event), flush=True)
        self.current_station_index = (self.current_station_index + 1) % len(self.route_sequence)
        self.current_direction = self.route_sequence[self.current_station_index][1]

    def hold_in(self, phase, sigma):
        if phase == "WAIT":
            super().hold_in(phase, sigma)
        else:
            super().hold_in(phase, 0)