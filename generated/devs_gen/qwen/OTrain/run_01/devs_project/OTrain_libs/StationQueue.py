"""StationQueue model for managing passenger boarding at train stations."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class StationQueue(Atomic):
    """Manages a FIFO queue of passengers waiting at a station to board the train."""

    def __init__(self, name: str, parent: Coupled | None, station_id: int, station_name: str, boarding_delay: float):
        super().__init__(name)
        self.parent = parent
        self.station_id = station_id
        self.station_name = station_name
        self.boarding_delay = boarding_delay
        self.add_in_port(Port(dict, "train_arrival"))
        self.add_in_port(Port(dict, "passenger_generated"))
        self.add_out_port(Port(dict, "passenger_boarding"))
        self.queue = []
        self.next_boarding_time = None
        self.current_passenger = None

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "event": event,
            "entity_type": "station_queue",
            "station_id": self.station_id,
            "station": self.station_name,
            "payload": payload,
        }), flush=True)

    def initialize(self):
        self.queue = []
        self.next_boarding_time = None
        self.current_passenger = None
        self.passivate("IDLE")

    def deltext(self, e):
        was_processing = self.phase == "PROCESSING"
        if was_processing:
            self.continuef(e)

        # Process all train_arrival events
        for train_event in self.input["train_arrival"].values:
            if train_event["station_id"] == self.station_id:
                # Start boarding process
                if not self.queue:
                    # No passengers waiting, do nothing
                    pass
                else:
                    # Start processing the queue
                    self._schedule_next_boarding()

        # Process all passenger_generated events
        for passenger_event in self.input["passenger_generated"].values:
            # Only add passengers whose origin matches this station and destination is different
            if passenger_event["origin"] == self.station_id and passenger_event["destination"] != self.station_id:
                self.queue.append(dict(passenger_event))

    def _schedule_next_boarding(self):
        if not self.queue:
            return
        # Schedule the next boarding event
        self.current_passenger = self.queue.pop(0)
        self.next_boarding_time = get_current_time() + self.boarding_delay
        self.hold_in("PROCESSING", self.boarding_delay)

    def lambdaf(self):
        if self.phase == "OUTPUT_READY" and self.current_passenger is not None:
            self.output["passenger_boarding"].add(dict(self.current_passenger))
            self._write_event("passenger_boarding", dict(self.current_passenger))

    def deltint(self):
        if self.phase == "PROCESSING":
            # Emit the current passenger boarding event
            self.hold_in("OUTPUT_READY", 0.0)
        elif self.phase == "OUTPUT_READY":
            # Clear the current passenger and check for more to process
            self.current_passenger = None
            if self.queue:
                # Continue with the next passenger
                self._schedule_next_boarding()
            else:
                # No more passengers, go back to idle
                self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass