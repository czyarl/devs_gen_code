from xdevs.models import Atomic, Coupled, Port
import random
import sys
import json
from devs_project.devs_utils.devs_context import get_current_time


class PassengerGenerator(Atomic):
    """Generate passengers at each station with stochastic intervals based on a Normal Distribution."""

    def __init__(self, name: str, parent: Coupled | None, initial_passenger_time: float,
                 mean_interval_minutes: float, std_interval_minutes: float,
                 min_interval_minutes: float, max_interval_minutes: float):
        super().__init__(name)
        self.parent = parent
        self.initial_passenger_time = initial_passenger_time
        self.mean_interval_minutes = mean_interval_minutes
        self.std_interval_minutes = std_interval_minutes
        self.min_interval_minutes = min_interval_minutes
        self.max_interval_minutes = max_interval_minutes
        
        # Station IDs and names
        self.stations = {1: "Bayview", 2: "Carling", 3: "Carleton", 4: "Confed", 5: "Greenboro"}
        
        # Internal state
        self.passenger_counts = [0] * 5  # passenger_num for each station (0 for initial)
        self.next_generation_times = [0.0] * 5  # next generation time for each station
        self.next_generation_intervals = [0.0] * 5  # next interval for each station
        
        # Add output port
        self.add_out_port(Port(dict, "passenger_generated"))

    def initialize(self):
        # Initialize passenger generation times
        for i in range(5):
            self.next_generation_times[i] = self.initial_passenger_time
            self.next_generation_intervals[i] = 0.0  # Will be set during first deltint()

        # Schedule initial passenger generation at t=0.5 for all stations
        # This is handled directly in lambdaf() for t=0.0
        self.hold_in("IDLE", 0.0)

    def deltext(self, e):
        # No input ports
        pass

    def lambdaf(self):
        # Emit all pending passenger generated events
        current_time = get_current_time()
        for i in range(5):
            if abs(self.next_generation_times[i] - current_time) < 1e-9:
                self._generate_passenger(i)

    def deltint(self):
        current_time = get_current_time()
        
        # Generate passengers at all stations that are due
        for i in range(5):
            if abs(self.next_generation_times[i] - current_time) < 1e-9:
                self._generate_passenger(i)
                
                # Schedule next generation
                interval_minutes = random.normalvariate(self.mean_interval_minutes, self.std_interval_minutes)
                interval_minutes = max(self.min_interval_minutes, min(self.max_interval_minutes, interval_minutes))
                interval_seconds = round(interval_minutes * 60)
                self.next_generation_times[i] = current_time + interval_seconds
                self.passenger_counts[i] += 1

        # Schedule the next event
        min_time = min(self.next_generation_times)
        if min_time < 10.0:  # Simulation ends at 10 seconds real time
            self.hold_in("IDLE", min_time - current_time)
        else:
            self.passivate("IDLE")

    def _generate_passenger(self, station_id):
        # Generate passenger ID and payload
        passenger_num = self.passenger_counts[station_id]
        origin = station_id + 1  # Station IDs are 1-based
        
        # Special case for initial passenger (ID=0)
        if passenger_num == 0:
            passenger_id = 0
        else:
            # Destination is uniformly selected from other 4 stations
            destinations = [s for s in range(1, 6) if s != origin]
            destination = random.choice(destinations)
            passenger_id = passenger_num * 100 + origin * 10 + destination
            
        payload = {
            'passenger_id': passenger_id,
            'passenger_num': passenger_num,
            'origin': origin,
            'destination': destination if passenger_num > 0 else 0  # Special case for initial passenger
        }
        
        # Emit the event to stdout as JSONL
        record = {
            "time": get_current_time(),
            "event": "passenger_generated",
            "entity_type": "passenger_generator",
            "station_id": origin,
            "station": self.stations[origin],
            "payload": payload
        }
        print(json.dumps(record), flush=True)
        
        # Emit to DEVS output port
        self.output["passenger_generated"].add(payload)

    def exit(self):
        pass