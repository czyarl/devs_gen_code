from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json
import sys


class StationQueue(Atomic):
    """Manage a FIFO queue of passengers waiting at a station to board the train."""

    def __init__(self, name: str, parent: Coupled | None, boarding_delay_seconds: float):
        super().__init__(name)
        self.parent = parent
        self.boarding_delay_seconds = boarding_delay_seconds
        self.add_in_port(Port(dict, "passenger_generated"))
        self.add_in_port(Port(dict, "train_arrival"))
        self.add_out_port(Port(dict, "passenger_boarding"))
        self.queue = []
        self.current_train_station = None
        self.current_train_direction = None
        self.boarding_start_time = None
        self.passenger_index = 0
        self.boarding_count = 0

    def initialize(self):
        self.queue = []
        self.current_train_station = None
        self.current_train_direction = None
        self.boarding_start_time = None
        self.passenger_index = 0
        self.boarding_count = 0
        self.passivate("IDLE")

    def deltext(self, e):
        # Process passenger_generated events
        for packet in self.input["passenger_generated"].values:
            passenger = packet
            if passenger["origin"] == self.current_train_station and passenger["origin"] != passenger["destination"]:
                self.queue.append(passenger)
        
        # Process train_arrival events
        for packet in self.input["train_arrival"].values:
            train_event = packet
            self.current_train_station = train_event["station"]
            self.current_train_direction = train_event["direction"]
            self.boarding_start_time = get_current_time()
            self.boarding_count = 0
            
            # Start boarding process immediately
            if self.queue:
                self.hold_in("BOARDING", self.boarding_delay_seconds)
            else:
                self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "BOARDING":
            if self.queue:
                passenger = self.queue.pop(0)
                # Prepare the passenger_boarding event
                boarding_event = {
                    "event": "passenger_boarding",
                    "time": get_current_time(),
                    "entity_type": "station_queue",
                    "station_id": self.current_train_station,
                    "station": self._get_station_name(self.current_train_station),
                    "payload": passenger
                }
                self.output["passenger_boarding"].add(boarding_event)
                print(json.dumps(boarding_event), flush=True)
                
                # Schedule next boarding
                if self.queue:
                    self.hold_in("BOARDING", self.boarding_delay_seconds)
                else:
                    self.passivate("IDLE")
            else:
                self.passivate("IDLE")

    def deltint(self):
        # No internal state changes required
        pass

    def exit(self):
        pass

    def _get_station_name(self, station_id):
        names = {1: "Bayview", 2: "Carling", 3: "Carleton", 4: "Confed", 5: "Greenboro"}
        return names.get(station_id, "Unknown")