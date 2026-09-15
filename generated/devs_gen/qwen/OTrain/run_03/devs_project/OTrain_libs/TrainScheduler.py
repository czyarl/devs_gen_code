from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json
import sys


class TrainScheduler(Atomic):
    def __init__(self, name: str, parent: Coupled | None, initial_arrival_time: float, travel_interval: int, route_stations: list):
        super().__init__(name)
        self.parent = parent
        self.initial_arrival_time = initial_arrival_time
        self.travel_interval = travel_interval
        self.route_stations = route_stations
        self.add_out_port(Port(dict, "train_arrival"))
        self.current_time = 0.0
        self.next_arrival_time = 0.0
        self.current_station_index = 0

    def initialize(self):
        self.current_time = 0.0
        self.next_arrival_time = self.initial_arrival_time
        self.current_station_index = 0
        self.hold_in("WAITING", 0.0)

    def deltext(self, e):
        # No input ports, so no action needed
        pass

    def lambdaf(self):
        if self.phase == "WAITING":
            # Emit train_arrival event
            station_id, direction = self.route_stations[self.current_station_index]
            arrival_event = {
                "time": self.next_arrival_time,
                "event": "train_arrival",
                "entity_type": "train",
                "station_id": station_id,
                "station": self._get_station_name(station_id),
                "payload": {
                    "station": station_id,
                    "direction": direction
                }
            }
            print(json.dumps(arrival_event), flush=True)
            self.output["train_arrival"].add({
                "station": station_id,
                "direction": direction
            })

    def deltint(self):
        if self.phase == "WAITING":
            # Move to next station
            self.current_station_index = (self.current_station_index + 1) % len(self.route_stations)
            self.next_arrival_time += self.travel_interval
            self.hold_in("WAITING", self.travel_interval)
        else:
            self.passivate()

    def exit(self):
        pass

    def _get_station_name(self, station_id):
        station_names = {
            1: "Bayview",
            2: "Carling",
            3: "Carleton",
            4: "Confed",
            5: "Greenboro"
        }
        return station_names.get(station_id, "Unknown")