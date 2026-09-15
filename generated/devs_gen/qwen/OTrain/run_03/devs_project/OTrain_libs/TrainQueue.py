"""TrainQueue: Manage passengers currently on the train, grouped by destination station."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class TrainQueue(Atomic):
    """Manage passengers currently on the train, grouped by destination station."""

    def __init__(self, name: str, parent: Coupled | None, alighting_delay_seconds: float):
        super().__init__(name)
        self.parent = parent
        self.alighting_delay_seconds = alighting_delay_seconds
        self.add_in_port(Port(dict, "passenger_boarding"))
        self.add_in_port(Port(dict, "train_arrival"))
        self.add_out_port(Port(dict, "passenger_exiting"))
        # Internal state: passengers currently on the train, grouped by destination
        self.passengers_by_destination = {}
        self.current_alight_event = None
        self.alighting_queue = []
        self.alighting_timer = None

    def _write_event(self, event: str, payload: dict) -> None:
        # Write a passenger_exiting event to stdout for each passenger who successfully alights
        record = {
            "time": get_current_time(),
            "event": event,
            "entity_type": "train_queue",
            "station_id": payload["origin"],
            "station": self._get_station_name(payload["origin"]),
            "payload": payload
        }
        print(json.dumps(record), flush=True)

    def _get_station_name(self, station_id: int) -> str:
        names = {1: "Bayview", 2: "Carling", 3: "Carleton", 4: "Confed", 5: "Greenboro"}
        return names.get(station_id, "Unknown")

    def initialize(self):
        self.passengers_by_destination = {}
        self.current_alight_event = None
        self.alighting_queue = []
        self.alighting_timer = None
        self.passivate("IDLE")

    def deltext(self, e):
        # Handle any incoming events
        if self.phase == "PROCESSING":
            self.continuef(e)

        # Process passenger_boarding events
        for boarding_event in self.input["passenger_boarding"].values:
            passenger = boarding_event
            destination = passenger["destination"]
            if destination not in self.passengers_by_destination:
                self.passengers_by_destination[destination] = []
            self.passengers_by_destination[destination].append(passenger)

        # Process train_arrival events
        for arrival_event in self.input["train_arrival"].values:
            station = arrival_event["station"]
            # Check if there are passengers destined for this station
            if station in self.passengers_by_destination:
                # Prepare alighting queue for passengers going to this station
                self.alighting_queue = self.passengers_by_destination[station]
                # Clear the destination list
                del self.passengers_by_destination[station]
                # Start processing alighting
                self._start_alighting_process()
            else:
                # No passengers going to this station, passivate
                self.passivate("IDLE")

    def _start_alighting_process(self):
        if not self.alighting_queue:
            self.passivate("IDLE")
            return
        # Start with the first passenger
        first_passenger = self.alighting_queue.pop(0)
        self._alight_passenger(first_passenger)

    def _alight_passenger(self, passenger: dict):
        # Emit the passenger_exiting event
        self._write_event("passenger_exiting", passenger)
        self.output["passenger_exiting"].add(passenger)
        # Schedule next alighting if there are more passengers
        if self.alighting_queue:
            self.hold_in("PROCESSING", self.alighting_delay_seconds)
        else:
            # No more passengers to alight, passivate
            self.passivate("IDLE")

    def lambdaf(self):
        # No output to emit in this model's lambdaf
        pass

    def deltint(self):
        if self.phase == "PROCESSING":
            if self.alighting_queue:
                # There are more passengers to alight
                next_passenger = self.alighting_queue.pop(0)
                self._alight_passenger(next_passenger)
            else:
                # No more passengers, passivate
                self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass