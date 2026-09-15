"""TrainQueue: Manages passengers currently on the train and handles their alighting process when the train reaches a destination station."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class TrainQueue(Atomic):
    """Manages passengers currently on the train and handles their alighting process."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "passenger_boarding"))
        self.add_in_port(Port(dict, "train_arrival"))
        self.add_out_port(Port(dict, "passenger_exiting"))
        self.passengers = []  # List of passengers currently on the train
        self.alighting_schedule = []  # List of (time, passenger) tuples for alighting
        self.current_station_id = None
        self.current_direction = None
        self.alighting_active = False
        self.next_alight_time = None

    def _write_event(self, event: str, payload: dict) -> None:
        """Write a JSONL record to stdout as required by external_io."""
        record = {
            "time": get_current_time(),
            "event": event,
            "entity_type": "train_queue",
            "station_id": self.current_station_id,
            "station": self._get_station_name(self.current_station_id),
            "payload": payload,
        }
        print(json.dumps(record), flush=True)

    def _get_station_name(self, station_id: int) -> str:
        """Map station ID to station name."""
        names = {1: "Bayview", 2: "Carling", 3: "Carleton", 4: "Confed", 5: "Greenboro"}
        return names.get(station_id, "Unknown")

    def initialize(self):
        self.passengers = []
        self.alighting_schedule = []
        self.current_station_id = None
        self.current_direction = None
        self.alighting_active = False
        self.next_alight_time = None
        self.passivate("IDLE")

    def deltext(self, e):
        # Handle train_arrival events
        for arrival in self.input["train_arrival"].values:
            self.current_station_id = arrival["station_id"]
            self.current_direction = arrival["direction"]
            self.alighting_active = True
            self.next_alight_time = get_current_time() + 0.025

            # Group passengers by destination
            destination_passengers = {}
            for p in self.passengers:
                dest = p["destination"]
                if dest not in destination_passengers:
                    destination_passengers[dest] = []
                destination_passengers[dest].append(p)

            # Schedule alighting for passengers going to current station
            if self.current_station_id in destination_passengers:
                passengers_to_alight = destination_passengers[self.current_station_id]
                self.alighting_schedule = []
                for i, p in enumerate(passengers_to_alight):
                    alight_time = self.next_alight_time + i * 0.025
                    self.alighting_schedule.append((alight_time, p))

                # Remove alighting passengers from train
                self.passengers = [p for p in self.passengers if p["destination"] != self.current_station_id]

                # Schedule first alighting event
                if self.alighting_schedule:
                    self.hold_in("ALIGHTING", self.alighting_schedule[0][0] - get_current_time())
                else:
                    self.passivate("IDLE")
            else:
                self.passivate("IDLE")

        # Handle passenger_boarding events
        for boarding in self.input["passenger_boarding"].values:
            self.passengers.append(dict(boarding))

    def lambdaf(self):
        if self.phase == "ALIGHTING" and self.alighting_schedule:
            # Emit the next passenger exiting
            _, passenger = self.alighting_schedule[0]
            self.output["passenger_exiting"].add(dict(passenger))
            self._write_event("passenger_exiting", dict(passenger))

    def deltint(self):
        if self.phase == "ALIGHTING" and self.alighting_schedule:
            # Remove the passenger we just emitted
            self.alighting_schedule.pop(0)
            if self.alighting_schedule:
                # Schedule next alighting
                next_time, _ = self.alighting_schedule[0]
                self.hold_in("ALIGHTING", next_time - get_current_time())
            else:
                # No more passengers to alight
                self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass