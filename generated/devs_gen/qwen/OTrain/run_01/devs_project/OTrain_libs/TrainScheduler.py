from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json
import sys


class TrainScheduler(Atomic):
    """Manages the train's movement schedule and generates train_arrival events at each station."""

    def __init__(self, name: str, parent: Coupled | None, initial_time: float, travel_interval: float, route_sequence: list):
        super().__init__(name)
        self.parent = parent
        self.initial_time = initial_time
        self.travel_interval = travel_interval
        self.route_sequence = route_sequence
        self.add_out_port(Port(dict, "train_arrival"))
        self.current_station_index = 0
        self.next_arrival_time = initial_time

    def initialize(self):
        # Emit initial train_arrival at t=0.0
        self.hold_in("EMIT_ARRIVAL", 0.0)

    def deltext(self, e):
        # This model has no input ports
        pass

    def lambdaf(self):
        if self.phase == "EMIT_ARRIVAL":
            current_time = get_current_time()
            station_id, direction = self.route_sequence[self.current_station_index]
            # Emit the train_arrival event
            event_data = {
                "event": "train_arrival",
                "time": current_time,
                "entity_type": "train",
                "station_id": station_id,
                "station": self._get_station_name(station_id),
                "payload": {
                    "station": station_id,
                    "direction": direction
                }
            }
            # Write to stdout as per external_io requirement
            print(json.dumps(event_data), flush=True)
            # Also write to DEVS output port
            self.output["train_arrival"].add({
                "station_id": station_id,
                "direction": direction
            })

    def deltint(self):
        if self.phase == "EMIT_ARRIVAL":
            # Move to next station
            self.current_station_index = (self.current_station_index + 1) % len(self.route_sequence)
            self.next_arrival_time += self.travel_interval
            # Schedule next arrival
            self.hold_in("EMIT_ARRIVAL", self.next_arrival_time - get_current_time())

    def exit(self):
        pass

    def _get_station_name(self, station_id):
        names = {1: "Bayview", 2: "Carling", 3: "Carleton", 4: "Confed", 5: "Greenboro"}
        return names.get(station_id, "Unknown")