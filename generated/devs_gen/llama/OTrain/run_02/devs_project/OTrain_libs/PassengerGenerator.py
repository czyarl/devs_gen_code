"""PassengerGenerator Atomic Model.

This model generates passengers at each of the 5 stations in the O-Train simulation.
It follows the locked interface and requirements specified in the problem description.
"""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import numpy as np

class PassengerGenerator(Atomic):
    """Generates passengers at each station."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "passenger_generated"))
        self.stations = 5
        self.passenger_num = {}

        # Initialize passenger_num for each station
        for i in range(1, self.stations + 1):
            self.passenger_num[i] = 0

        self.rng = np.random.default_rng()

    def initialize(self):
        # Schedule initial passenger generation at t=0.5 for all stations
        self.hold_in("GENERATE", 0.5)

    def deltext(self, e):
        return None

    def lambdaf(self):
        if self.phase != "GENERATE":
            return

        # Generate a new passenger
        station = int(self.phase)
        self.passenger_num[station] += 1
        passenger_num = self.passenger_num[station]

        # Calculate passenger ID
        destination = self.rng.integers(1, self.stations + 1, endpoint=True)
        while destination == station:
            destination = self.rng.integers(1, self.stations + 1, endpoint=True)
        passenger_id = passenger_num * 100 + station * 10 + destination

        # Create passenger event
        event_time = get_current_time()
        passenger_event = {
            "passenger_id": passenger_id,
            "passenger_num": passenger_num,
            "origin": station,
            "destination": destination,
        }

        # Emit passenger_generated event
        self.output["passenger_generated"].add(passenger_event)

        # Schedule next passenger generation
        interval = self.rng.normal(300, 300)  # Normal distribution with mean 300 and std 300
        interval = max(60, min(540, interval))  # Clamp interval to [60, 540] seconds
        interval = round(interval)  # Round to nearest integer seconds
        self.hold_in("GENERATE", interval)

    def deltint(self):
        if self.phase != "GENERATE":
            self.passivate()
            return

    def exit(self):
        pass