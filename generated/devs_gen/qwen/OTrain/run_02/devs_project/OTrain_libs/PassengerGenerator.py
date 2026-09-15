from xdevs.models import Atomic, Coupled, Port
import json
import random
import sys
from devs_project.devs_utils.devs_context import get_current_time

class PassengerGenerator(Atomic):
    def __init__(self, name: str, parent: Coupled | None, initial_arrival_time: float, mean_interval_minutes: float, std_interval_minutes: float, interval_min_minutes: float, interval_max_minutes: float):
        super().__init__(name)
        self.parent = parent
        self.initial_arrival_time = initial_arrival_time
        self.mean_interval_minutes = mean_interval_minutes
        self.std_interval_minutes = std_interval_minutes
        self.interval_min_minutes = interval_min_minutes
        self.interval_max_minutes = interval_max_minutes
        
        # Station configuration
        self.stations = {
            1: "Bayview",
            2: "Carling",
            3: "Carleton",
            4: "Confed",
            5: "Greenboro"
        }
        
        # Internal state
        self.passenger_num = 0
        self.next_generation_time = {}
        self.next_passenger_id = 0
        
        # Initialize output port
        self.add_out_port(Port(dict, "passenger_generated"))
        
        # Initialize random seed
        random.seed(get_current_time())

    def initialize(self):
        # Initialize the generation time for each station at t=0.5
        for station_id in self.stations:
            self.next_generation_time[station_id] = self.initial_arrival_time
        # Schedule the initial passenger generation at t=0.5
        self.hold_in("IDLE", self.initial_arrival_time)

    def deltext(self, e):
        # This model has no input ports
        pass

    def lambdaf(self):
        # Emit the passenger generated event
        if self.phase == "OUTPUT_READY":
            # Emit all passengers that are ready to be generated
            current_time = get_current_time()
            for station_id in self.stations:
                if self.next_generation_time[station_id] == current_time:
                    # Generate a passenger
                    passenger_id = 0 if self.passenger_num == 0 else self.next_passenger_id
                    origin = station_id
                    destination = random.choice([s for s in self.stations if s != origin])
                    
                    # Create passenger data
                    passenger_data = {
                        'passenger_id': passenger_id,
                        'passenger_num': self.passenger_num,
                        'origin': origin,
                        'destination': destination
                    }
                    
                    # Emit the passenger generated event
                    self.output["passenger_generated"].add(passenger_data)
                    
                    # Emit to stdout as required
                    record = {
                        'time': current_time,
                        'event': 'passenger_generated',
                        'entity_type': 'passenger_generator',
                        'station_id': station_id,
                        'station': self.stations[station_id],
                        'payload': passenger_data
                    }
                    print(json.dumps(record), flush=True)
                    
                    # Update passenger ID and number
                    if self.passenger_num == 0:
                        self.passenger_num += 1
                        self.next_passenger_id += 100
                    else:
                        self.next_passenger_id += 100
                        
                    # Schedule next generation
                    interval = random.normalvariate(self.mean_interval_minutes, self.std_interval_minutes)
                    interval = max(self.interval_min_minutes, min(self.interval_max_minutes, interval))
                    interval_seconds = round(interval * 60)
                    self.next_generation_time[station_id] += interval_seconds
                    
                    # Reset passenger_num to 1 after initial passenger
                    if self.passenger_num == 0:
                        self.passenger_num = 1

    def deltint(self):
        # Check for any scheduled passenger generation
        current_time = get_current_time()
        next_event_time = float('inf')
        for station_id in self.stations:
            if self.next_generation_time[station_id] > current_time:
                next_event_time = min(next_event_time, self.next_generation_time[station_id])
        
        # If there's no next event, passivate
        if next_event_time == float('inf'):
            self.passivate()
        else:
            # Schedule next event
            self.hold_in("OUTPUT_READY", next_event_time - current_time)

    def exit(self):
        pass