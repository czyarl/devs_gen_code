"""TrainScheduler Atomic DEVS Model.

This model controls the movement of the single train across the network and
generates train_arrival events.
"""

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json
import sys


class TrainScheduler(Atomic):
    """Train Scheduler Atomic Model."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "train_arrival"))

        # Station configuration
        self.stations = [1, 2, 3, 4, 5]
        self.directions = [0, 1]
        self.route_sequence = [
            (1, 0), (2, 0), (3, 0), (4, 0), (5, 1),
            (4, 1), (3, 1), (2, 1), (1, 0)
        ]

        # Train properties
        self.train_position = 0  # Current position in route_sequence
        self.train_direction = 0  # Current direction (0 or 1)
        self.travel_interval = 225.0  # seconds

        # Initialization
        self.current_time = 0.0

    def initialize(self):
        self.current_time = get_current_time()
        self.train_position = 0
        self.train_direction = 0
        self.output["train_arrival"].add({
            "station": self.route_sequence[self.train_position][0],
            "direction": self.route_sequence[self.train_position][1]
        })
        self.hold_in("WAITING", self.travel_interval)

    def deltext(self, e):
        return None

    def lambdaf(self):
        if self.phase == "WAITING":
            self.train_position = (self.train_position + 1) % len(self.route_sequence)
            self.train_direction = self.route_sequence[self.train_position][1]
            self.output["train_arrival"].add({
                "station": self.route_sequence[self.train_position][0],
                "direction": self.route_sequence[self.train_position][1]
            })
            self.hold_in("WAITING", self.travel_interval)

    def deltint(self):
        pass

    def exit(self):
        # Write final external IO if required
        pass

    def external_io(self):
        # No external IO for this model
        pass