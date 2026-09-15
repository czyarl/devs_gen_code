"""Complete implementation of the PassengerGenerator model."""

import json
import numpy as np
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class PassengerGenerator(Atomic):
    """Generate passengers at stations according to a stochastic process."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "passenger_generated"))

    def initialize(self):
        self.passenger_num = 0
        self.stations = [1, 2, 3, 4, 5]
        self.normal_dist = np.random.normal(loc=5.0 * 60, scale=5.0 * 60, size=10000)
        self.generated_at = 0.0
        self.generated_at = get_current_time()
        if self.generated_at < 0.5:
            self.generated_at = 0.5
        self.schedule_initial_passengers()

    def schedule_initial_passengers(self):
        for station in self.stations:
            self.generate_passenger(self.generated_at, station, station, 0)

    def generate_passenger(self, time, origin, destination, passenger_num):
        passenger_id = self.calculate_passenger_id(passenger_num, origin, destination)
        event = {
            "event": "passenger_generated",
            "time": time,
            "entity_type": "passenger_generator",
            "payload": {
                "passenger_id": passenger_id,
                "passenger_num": passenger_num,
                "origin": origin,
                "destination": destination
            }
        }
        self.output["passenger_generated"].add(event)
        print(json.dumps(event), flush=True)

    def calculate_passenger_id(self, passenger_num, origin, destination):
        return passenger_num * 100 + origin * 10 + destination

    def deltint(self):
        interval = self.get_interval()
        self.generated_at += interval
        self.passenger_num += 1
        self.generate_passenger(self.generated_at, origin, destination, self.passenger_num)

    def get_interval(self):
        interval = np.random.normal(loc=5.0 * 60, scale=5.0 * 60)
        interval = max(1.0 * 60, min(interval, 9.0 * 60))
        interval = round(interval)
        return interval

    def lambdaf(self):
        pass

    def deltext(self, e):
        pass

    def exit(self):
        pass