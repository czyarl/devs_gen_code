"""TrainScheduler atomic model implementation.

This model controls the movement of a single train across the network,
generating 'train_arrival' events at each station stop based on a predefined
route sequence and travel intervals.

(c) 2024 xDEVS Project
"""

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json
import sys


class TrainScheduler(Atomic):
    """Train Scheduler atomic model.

    Controls the movement of a single train across the network,
    generating 'train_arrival' events at each station stop.

    The train's movement is based on a predefined route sequence and travel intervals.
    The model starts at Bayview station at time 0.0 and moves according to the
    specified route and timing requirements.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "train_arrival"))

        # Route sequence and travel intervals
        self.route = [
            (1, 0),  # Bayview (1, dir=0)
            (2, 0),  # Carling (2, 0)
            (3, 0),  # Carleton (3, 0)
            (4, 0),  # Confed (4, 0)
            (5, 1),  # Greenboro (5, 1)
            (4, 1),  # Confed (4, 1)
            (3, 1),  # Carleton (3, 1)
            (2, 1),  # Carling (2, 1)
            (1, 0),  # Bayview (1, 0)
        ]
        self.travel_interval = 225.0  # seconds

        # Initial state
        self.current_station = 1
        self.current_direction = 0
        self.next_station_index = 0

    def initialize(self):
        # Schedule the first train arrival at Bayview at t=0.0
        self.output["train_arrival"].add({
            "station_id": self.current_station,
            "direction": self.current_direction,
        })
        self.hold_in("WAIT", self.travel_interval)

    def deltext(self, e):
        # No external inputs
        pass

    def lambdaf(self):
        # No output in this phase
        pass

    def deltint(self):
        if self.phase != "WAIT":
            return

        # Move to the next station in the route
        self.current_station, self.current_direction = self.route[self.next_station_index]
        self.next_station_index = (self.next_station_index + 1) % len(self.route)

        # Generate train arrival event
        self.output["train_arrival"].add({
            "station_id": self.current_station,
            "direction": self.current_direction,
        })

        # Schedule the next train arrival
        self.hold_in("WAIT", self.travel_interval)

    def exit(self):
        # Write final output to stdout if required
        pass