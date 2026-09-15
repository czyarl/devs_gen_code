from xdevs.models import Atomic, Coupled, Port
import json
import sys

from devs_project.devs_utils.devs_context import get_current_time


class Train(Atomic):
    """Train model controlling movement along a fixed route."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        route_sequence: list,
        travel_interval: float,
        alighting_delay: float,
        station_names: dict,
    ):
        super().__init__(name)
        self.parent = parent
        self.route_sequence = route_sequence
        self.travel_interval = travel_interval
        self.alighting_delay = alighting_delay
        self.station_names = station_names

        # Ports
        self.add_in_port(Port(dict, "passenger_boarded_in"))
        self.add_out_port(Port(dict, "train_arrival_out"))

        # State
        self.route_index = 0
        self.on_board_passengers = []  # List of dicts
        self.departure_deadline = 0.0
        self.arrival_time = 0.0
        self.current_station_id = 0
        self.current_direction = 0
        self.current_station_name = ""
        self.exiting_passenger = None

    def initialize(self):
        # Startup: t=0.0 at first station (Bayview)
        self.route_index = 0
        self.on_board_passengers = []
        self.exiting_passenger = None
        
        # Set current station info
        self.current_station_id, self.current_direction = self.route_sequence[0]
        self.current_station_name = self.station_names[self.current_station_id]
        
        # Initial arrival event logic
        self.arrival_time = 0.0
        self.hold_in("ARRIVAL_EMIT", 0.0)

    def deltext(self, e: float):
        # External input: passenger_boarded_in
        # Only relevant during BOARDING phase
        if self.phase == "BOARDING":
            remaining_time = max(0.0, self.ta() - e)
            
            # Process all incoming passengers
            for p in self.input["passenger_boarded_in"].values:
                self.on_board_passengers.append(dict(p))
            
            # Remain in BOARDING phase until the deadline is reached.
            self.hold_in("BOARDING", remaining_time)

    def lambdaf(self):
        now = get_current_time()

        if self.phase == "ARRIVAL_EMIT":
            # Generate train_arrival event
            payload = {
                "station": self.current_station_id,
                "direction": self.current_direction
            }
            
            # 1. DEVS Output
            self.output["train_arrival_out"].add(payload)
            
            # 2. External IO (stdout)
            record = {
                "time": now,
                "event": "train_arrival",
                "entity_type": "train",
                "station_id": self.current_station_id,
                "station": self.current_station_name,
                "payload": payload
            }
            print(json.dumps(record), flush=True)

        elif self.phase == "ALIGHTING":
            # Emit passenger_exiting event for the passenger currently being processed
            if self.exiting_passenger is not None:
                p = self.exiting_passenger
                record = {
                    "time": now,
                    "event": "passenger_exiting",
                    "entity_type": "train_queue",
                    "station_id": self.current_station_id,
                    "station": self.current_station_name,
                    "payload": {
                        "passenger_id": p["passenger_id"],
                        "passenger_num": p["passenger_num"],
                        "origin": p["origin"],
                        "destination": p["destination"]
                    }
                }
                print(json.dumps(record), flush=True)

    def deltint(self):
        now = get_current_time()

        if self.phase == "ARRIVAL_EMIT":
            # After emitting arrival, transition to ALIGHTING
            self._schedule_next_alighting_or_boarding()

        elif self.phase == "ALIGHTING":
            # We just emitted an exiting event.
            # Remove the passenger we just emitted from the manifest
            if self.exiting_passenger in self.on_board_passengers:
                self.on_board_passengers.remove(self.exiting_passenger)
            
            # Schedule next alighting or move to boarding
            self._schedule_next_alighting_or_boarding()

        elif self.phase == "BOARDING":
            # Departure deadline reached. Move to TRAVEL.
            # Advance route index
            self.route_index = (self.route_index + 1) % len(self.route_sequence)
            
            # Next station info
            next_station_id, next_direction = self.route_sequence[self.route_index]
            
            # Calculate travel duration
            travel_duration = self.travel_interval - (now - self.arrival_time)
            
            # Update state for next station
            self.current_station_id = next_station_id
            self.current_direction = next_direction
            self.current_station_name = self.station_names[next_station_id]
            
            self.hold_in("TRAVEL", travel_duration)

        elif self.phase == "TRAVEL":
            # Arrived at next station
            self.arrival_time = now
            self.hold_in("ARRIVAL_EMIT", 0.0)

    def _schedule_next_alighting_or_boarding(self):
        """Helper to determine next phase after arrival or after an alighting event."""
        now = get_current_time()
        
        # Find next passenger to alight
        next_alighting = None
        for p in self.on_board_passengers:
            if p["destination"] == self.current_station_id:
                next_alighting = p
                break
        
        if next_alighting is not None:
            # Check if we have time to alight
            deadline = self.arrival_time + self.travel_interval
            time_left = deadline - now
            
            if time_left >= self.alighting_delay:
                self.exiting_passenger = next_alighting
                self.hold_in("ALIGHTING", self.alighting_delay)
            else:
                # Not enough time to alight, proceed to boarding/travel
                self._start_boarding_phase(deadline)
        else:
            # No more alighting passengers
            self._start_boarding_phase(self.arrival_time + self.travel_interval)

    def _start_boarding_phase(self, deadline):
        self.departure_deadline = deadline
        now = get_current_time()
        wait_time = self.departure_deadline - now
        
        if wait_time > 0.0:
            self.hold_in("BOARDING", wait_time)
        else:
            self.hold_in("BOARDING", 0.0)

    def exit(self):
        pass