"""Complete implementation of the StationQueue model using xdevs.py."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class StationQueue(Atomic):
    """Manages passengers waiting at a station to board the train."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "train_arrival"))
        self.add_in_port(Port(dict, "passenger_generated"))
        self.add_out_port(Port(dict, "passenger_boarding"))
        self.add_out_port(Port(dict, "passenger_exiting"))
        self.passenger_queue = []
        self.current_train_direction = None
        self.current_train_station = None

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "event": event,
            "entity_type": "station_queue",
            "station_id": self.current_train_station,
            "station": {1: "Bayview", 2: "Carling", 3: "Carleton", 4: "Confed", 5: "Greenboro"}[self.current_train_station],
            "payload": payload,
        }), flush=True)

    def initialize(self):
        self.passenger_queue = []
        self.current_train_direction = None
        self.current_train_station = None
        self.passivate("IDLE")

    def deltext(self, e):
        for item in self.input["passenger_generated"].values:
            passenger = item["payload"]
            if passenger["origin"] == self.current_train_station and passenger["origin"] != passenger["destination"]:
                self.passenger_queue.append(passenger)
                self._write_event("passenger_arrival", passenger)

        for item in self.input["train_arrival"].values:
            train = item["payload"]
            if train["station"] == self.current_train_station:
                self.current_train_direction = train["direction"]
                self._process_passengers()

    def _process_passengers(self):
        if self.passenger_queue:
            passenger = self.passenger_queue.pop(0)
            self._write_event("passenger_boarding", {
                "passenger_id": passenger["passenger_id"],
                "passenger_num": passenger["passenger_num"],
                "origin": passenger["origin"],
                "destination": passenger["destination"],
            })
            self.hold_in("BOARDING", 0.025)
        else:
            self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "BOARDING":
            self.output["passenger_boarding"].add({
                "passenger_id": self.passenger_queue[0]["passenger_id"],
                "passenger_num": self.passenger_queue[0]["passenger_num"],
                "origin": self.passenger_queue[0]["origin"],
                "destination": self.passenger_queue[0]["destination"],
            })

    def deltint(self):
        if self.phase == "BOARDING":
            self.passenger_queue.pop(0)
            self._write_event("passenger_exiting", {
                "passenger_id": self.passenger_queue[0]["passenger_id"],
                "passenger_num": self.passenger_queue[0]["passenger_num"],
                "origin": self.passenger_queue[0]["origin"],
                "destination": self.passenger_queue[0]["destination"],
            })
            if self.passenger_queue:
                self.hold_in("BOARDING", 0.025)
            else:
                self.passivate("IDLE")

    def exit(self):
        pass