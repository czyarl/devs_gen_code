"""Atomic DEVS model for managing passengers on the train and handling alighting."""

import json
from collections import defaultdict
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class TrainQueue(Atomic):
    """Manages passengers currently on the train, grouping them by destination.
    Handles alighting when the train arrives at a station.
    """

    def __init__(self, name: str, parent: Coupled | None, alighting_delay: float):
        super().__init__(name)
        self.parent = parent
        self.alighting_delay = alighting_delay
        self.add_in_port(Port(dict, "train_arrival"))
        self.add_in_port(Port(dict, "passenger_boarding"))
        self.add_out_port(Port(dict, "passenger_exiting"))
        # Internal state
        self.passengers_by_destination = defaultdict(list)
        self.current_station = None
        self.current_direction = None
        self.alighting_queue = []
        self.alighting_timer = None
        self.payload_to_send = None

    def _write_passenger_exiting(self, passenger: dict) -> None:
        """Write a passenger_exiting event to stdout."""
        print(json.dumps({
            "time": get_current_time(),
            "event": "passenger_exiting",
            "entity_type": "train_queue",
            "station_id": passenger["origin"],
            "station": self._get_station_name(passenger["origin"]),
            "payload": passenger,
        }), flush=True)

    def _get_station_name(self, station_id: int) -> str:
        """Map station ID to station name."""
        names = {
            1: "Bayview",
            2: "Carling",
            3: "Carleton",
            4: "Confed",
            5: "Greenboro"
        }
        return names.get(station_id, "Unknown")

    def initialize(self):
        self.passengers_by_destination = defaultdict(list)
        self.current_station = None
        self.current_direction = None
        self.alighting_queue = []
        self.alighting_timer = None
        self.payload_to_send = None
        self.passivate("IDLE")

    def deltext(self, e):
        # Update internal clock
        if self.phase == "ALIGHTING":
            self.continuef(e)

        # Process incoming train_arrival events
        for arrival in self.input["train_arrival"].values:
            self.current_station = arrival["station_id"]
            self.current_direction = arrival["direction"]
            # Start alighting process
            self._start_alighting()

        # Process incoming passenger_boarding events
        for boarding in self.input["passenger_boarding"].values:
            destination = boarding["destination"]
            self.passengers_by_destination[destination].append(boarding)

    def _start_alighting(self):
        """Start the alighting process for passengers going to current station."""
        self.alighting_queue = self.passengers_by_destination[self.current_station]
        if self.alighting_queue:
            self.hold_in("ALIGHTING", self.alighting_delay)
        else:
            # No passengers to alight
            self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "OUTPUT_READY" and self.payload_to_send is not None:
            self.output["passenger_exiting"].add(dict(self.payload_to_send))
            self._write_passenger_exiting(dict(self.payload_to_send))

    def deltint(self):
        if self.phase == "ALIGHTING":
            if self.alighting_queue:
                # Pop the next passenger to alight
                passenger = self.alighting_queue.pop(0)
                self.payload_to_send = dict(passenger)
                self.hold_in("OUTPUT_READY", 0.0)
            else:
                # All passengers alighted
                self.passivate("IDLE")
        elif self.phase == "OUTPUT_READY":
            self.payload_to_send = None
            # Remove the alighted passenger from the internal list
            self.passengers_by_destination[self.current_station].remove(dict(self.payload_to_send))
            # Check if there are more passengers to alight
            if self.alighting_queue:
                self.hold_in("ALIGHTING", self.alighting_delay)
            else:
                self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass