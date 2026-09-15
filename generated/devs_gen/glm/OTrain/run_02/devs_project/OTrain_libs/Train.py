import json
import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class Train(Atomic):
    """
    Manages the train's position along the fixed route sequence and the passenger manifest.
    Starts at t=0.0 at Bayview (Station 1, Direction 0).
    """

    # Constants
    TRAVEL_INTERVAL = 225.0
    ALIGHTING_DELAY = 0.025

    # Station Names Mapping
    STATION_NAMES = {
        1: "Bayview",
        2: "Carling",
        3: "Carleton",
        4: "Confed",
        5: "Greenboro",
    }

    # Route Sequence: (Station ID, Direction)
    # Bayview(1,0) -> Carling(2,0) -> Carleton(3,0) -> Confed(4,0) -> Greenboro(5,1)
    # -> Confed(4,1) -> Carleton(3,1) -> Carling(2,1) -> Bayview(1,0)
    ROUTE = [
        (1, 0),
        (2, 0),
        (3, 0),
        (4, 0),
        (5, 1),
        (4, 1),
        (3, 1),
        (2, 1),
        (1, 0),
    ]

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Ports
        self.add_in_port(Port(dict, "boarding_in"))
        self.add_out_port(Port(dict, "arrival_out"))

        # Internal State
        self.route_index = 0  # Points to current station in ROUTE
        self.passenger_manifest = []  # List of passenger dicts

    def initialize(self):
        # Start at Bayview (index 0).
        # We initialize in TRAVELING with sigma=0 to trigger the "Initial Arrival" event immediately.
        # This allows us to emit the arrival event for Bayview at t=0.0 before entering the normal cycle.
        self.route_index = 0
        self.passenger_manifest = []
        self.hold_in("TRAVELING", 0.0)

    def deltext(self, e: float):
        # Input Handling: The model accepts passenger data via the 'boarding_in' port at any time.
        # Received passengers are immediately appended to the internal manifest.
        # External inputs do not interrupt or reset the timers for the current internal phase.
        for passenger in self.input["boarding_in"].values:
            self.passenger_manifest.append(passenger)
        
        # Preserve the current phase and remaining time
        if self.phase != "passive":
            self.continuef(e)

    def lambdaf(self):
        if self.phase == "TRAVELING":
            # We are at a station arrival point.
            # 1. Emit arrival info via the 'arrival_out' port.
            station_id, direction = self.ROUTE[self.route_index]
            payload = {
                "time": get_current_time(),
                "station_id": station_id,
                "direction": direction
            }
            self.output["arrival_out"].add(payload)

            # 2. Write 'train_arrival' JSONL record to stdout.
            record = {
                "time": get_current_time(),
                "event": "train_arrival",
                "entity_type": "train",
                "station_id": station_id,
                "station": self.STATION_NAMES[station_id],
                "payload": {
                    "station": station_id,
                    "direction": direction
                }
            }
            print(json.dumps(record), flush=True)

    def deltint(self):
        if self.phase == "TRAVELING":
            # We have just emitted an arrival event for the station at self.route_index.
            # Now we transition to ALIGHTING to process passengers getting off.
            # We check if there are passengers destined for the current station.
            station_id, _ = self.ROUTE[self.route_index]
            passengers_to_alight = [p for p in self.passenger_manifest if p['destination'] == station_id]
            
            if passengers_to_alight:
                # Passengers exist, schedule the first alighting transition (0.025s).
                self.hold_in("ALIGHTING", self.ALIGHTING_DELAY)
            else:
                # No passengers, immediately transition to TRAVELING phase logic.
                # This means we update the route index to the next station and schedule the travel interval.
                self.route_index = (self.route_index + 1) % len(self.ROUTE)
                self.hold_in("TRAVELING", self.TRAVEL_INTERVAL)

        elif self.phase == "ALIGHTING":
            # We are in the ALIGHTING phase. An internal transition has fired.
            # This means we need to process one passenger alighting.
            station_id, _ = self.ROUTE[self.route_index]
            
            # Find and remove one passenger destined for this station.
            # We iterate to find the first match.
            passenger_to_remove = None
            for i, p in enumerate(self.passenger_manifest):
                if p['destination'] == station_id:
                    passenger_to_remove = p
                    self.passenger_manifest.pop(i)
                    break
            
            # If a passenger was found (which should be true if we are here), write the exiting record.
            if passenger_to_remove:
                record = {
                    "time": get_current_time(),
                    "event": "passenger_exiting",
                    "entity_type": "train_queue",
                    "station_id": station_id,
                    "station": self.STATION_NAMES[station_id],
                    "payload": {
                        "passenger_id": passenger_to_remove['passenger_id'],
                        "passenger_num": passenger_to_remove['passenger_num'],
                        "origin": passenger_to_remove['origin'],
                        "destination": passenger_to_remove['destination']
                    }
                }
                print(json.dumps(record), flush=True)
            
            # Check if more passengers remain for this station.
            remaining_passengers = [p for p in self.passenger_manifest if p['destination'] == station_id]
            
            if remaining_passengers:
                # Schedule the next alighting transition.
                self.hold_in("ALIGHTING", self.ALIGHTING_DELAY)
            else:
                # No more passengers. We are done at this station.
                # Update the route index to the next station and schedule the travel interval.
                self.route_index = (self.route_index + 1) % len(self.ROUTE)
                self.hold_in("TRAVELING", self.TRAVEL_INTERVAL)

    def exit(self):
        pass