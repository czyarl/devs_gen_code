"""StationQueue: Manages a FIFO queue of passengers waiting to board at a station."""

import json
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class StationQueue(Atomic):
    """Manages a FIFO queue of passengers waiting to board at a station."""

    def __init__(self, name: str, parent: Coupled | None, station_id: int, station_name: str):
        super().__init__(name)
        self.parent = parent
        self.station_id = station_id
        self.station_name = station_name
        self.add_in_port(Port(dict, "passenger_arrival"))
        self.add_in_port(Port(dict, "train_arrival"))
        self.add_out_port(Port(dict, "passenger_boarding"))
        self.queue = deque()
        self.boarding_start_time = None
        self.passenger_num = 0
        self.payload_to_send = None

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
        self.queue = deque()
        self.boarding_start_time = None
        self.passenger_num = 0
        self.payload_to_send = None
        self.passivate("IDLE")

    def deltext(self, e):
        # Process train arrival
        for train_event in self.input["train_arrival"].values:
            self.boarding_start_time = get_current_time()
            # Start boarding process
            if self.queue:
                # Delay the first boarding by 0.025s
                self.hold_in("BOARDING", 0.025)
            else:
                # If no passengers, just passivate
                self.passivate("IDLE")

        # Process passenger arrivals
        for passenger in self.input["passenger_arrival"].values:
            # Validate that the passenger's origin matches the station
            if passenger['origin'] == self.station_id and passenger['destination'] != self.station_id:
                self.queue.append(passenger)
                # If we're not boarding, and this is the first passenger, start boarding after delay
                if self.phase == "IDLE" and self.queue:
                    self.hold_in("BOARDING", 0.025)
            # If passenger doesn't match, silently drop (not added to queue)

    def lambdaf(self):
        if self.phase == "OUTPUT_READY" and self.payload_to_send is not None:
            self.output["passenger_boarding"].add(dict(self.payload_to_send))

    def deltint(self):
        if self.phase == "BOARDING":
            if self.queue:
                # Take the next passenger from the queue
                passenger = self.queue.popleft()
                # Record the boarding event
                self._write_event("passenger_boarding", passenger)
                # Prepare output
                self.payload_to_send = dict(passenger)
                self.hold_in("OUTPUT_READY", 0.0)
            else:
                # No more passengers to board
                self.passivate("IDLE")
        elif self.phase == "OUTPUT_READY":
            # Clear the payload and check if there's another passenger to board
            self.payload_to_send = None
            if self.queue:
                # Schedule next boarding after 0.025s delay
                self.hold_in("BOARDING", 0.025)
            else:
                self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass