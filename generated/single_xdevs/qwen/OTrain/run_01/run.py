# Your complete run.py implementation here
import argparse
import sys
import json
import logging
import random
import time
import math
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Set seed for reproducibility
random.seed(time.time_ns())
numpy_seed = time.time_ns() % (2**32 - 1)
try:
    import numpy as np
    np.random.seed(numpy_seed)
except ImportError:
    pass

# Station configuration
STATIONS = {
    1: "Bayview",
    2: "Carling",
    3: "Carleton",
    4: "Confed",
    5: "Greenboro"
}

# Route sequence
ROUTE = [
    (1, 0), (2, 0), (3, 0), (4, 0), (5, 1),
    (4, 1), (3, 1), (2, 1), (1, 0)
]

class PassengerGenerator(Atomic):
    def __init__(self, station_id, parent):
        super().__init__(f"passenger_generator_{station_id}")
        self.parent = parent
        self.station_id = station_id
        self.station_name = STATIONS[station_id]
        self.passenger_num = 0
        self.passenger_queue = deque()
        self.next_generation_time = 0.0
        self.active = True
        
        # Ports
        self.in_port = Port(object, "in_port")
        self.out_port = Port(object, "out_port")
        self.add_in_port(self.in_port)
        self.add_out_port(self.out_port)
        
        # Initialize
        self.hold_in("INIT", 0)
    
    def initialize(self):
        # Generate initial passenger (ID=0) at t=0.5
        self.passenger_num = 0
        payload = {
            "passenger_id": 0,
            "passenger_num": self.passenger_num,
            "origin": self.station_id,
            "destination": None
        }
        event = {
            "time": 0.5,
            "event": "passenger_generated",
            "entity_type": "passenger_generator",
            "station_id": self.station_id,
            "station": self.station_name,
            "payload": payload
        }
        print(json.dumps(event), file=sys.stdout, flush=True)
        
        # Schedule next passenger generation
        self.passenger_num += 1
        self.schedule_next_generation()
    
    def schedule_next_generation(self):
        # Generate interval from normal distribution
        interval = random.normalvariate(5.0 * 60, 5.0 * 60)  # Mean 5 min, std 5 min
        interval = max(1 * 60, min(9 * 60, interval))  # Clamp to [1, 9] minutes
        interval = round(interval)  # Round to nearest second
        
        self.next_generation_time = self.get_time() + interval
        self.hold_in("WAITING", interval)
    
    def lambdaf(self):
        # No output in this model
        pass
    
    def deltint(self):
        # Generate a new passenger
        # Generate destination (different from origin)
        destinations = [i for i in range(1, 6) if i != self.station_id]
        destination = random.choice(destinations)
        
        # Calculate passenger ID
        passenger_id = self.passenger_num * 100 + self.station_id * 10 + destination
        
        payload = {
            "passenger_id": passenger_id,
            "passenger_num": self.passenger_num,
            "origin": self.station_id,
            "destination": destination
        }
        
        event = {
            "time": self.get_time(),
            "event": "passenger_generated",
            "entity_type": "passenger_generator",
            "station_id": self.station_id,
            "station": self.station_name,
            "payload": payload
        }
        print(json.dumps(event), file=sys.stdout, flush=True)
        
        # Schedule next passenger generation
        self.passenger_num += 1
        self.schedule_next_generation()
    
    def deltext(self, e):
        # No external transitions
        self.hold_in("WAITING", self.sigma)
    
    def exit(self):
        pass

class StationQueue(Atomic):
    def __init__(self, station_id, parent):
        super().__init__(f"station_queue_{station_id}")
        self.parent = parent
        self.station_id = station_id
        self.station_name = STATIONS[station_id]
        self.passenger_queue = deque()
        self.boarding = False
        self.boarding_start_time = 0.0
        self.boarding_count = 0
        
        # Ports
        self.in_port = Port(object, "in_port")
        self.out_port = Port(object, "out_port")
        self.train_arrival_port = Port(object, "train_arrival_port")
        self.add_in_port(self.in_port)
        self.add_in_port(self.train_arrival_port)
        self.add_out_port(self.out_port)
        
        # Initialize
        self.hold_in("IDLE", float('inf'))
    
    def initialize(self):
        self.hold_in("IDLE", float('inf'))
    
    def lambdaf(self):
        # No output in this model
        pass
    
    def deltint(self):
        if self.boarding:
            # Process boarding
            if self.passenger_queue:
                # Board next passenger
                passenger = self.passenger_queue.popleft()
                boarding_delay = 0.025 * self.boarding_count
                event_time = self.boarding_start_time + boarding_delay
                
                payload = {
                    "passenger_id": passenger["passenger_id"],
                    "passenger_num": passenger["passenger_num"],
                    "origin": passenger["origin"],
                    "destination": passenger["destination"]
                }
                
                event = {
                    "time": event_time,
                    "event": "passenger_boarding",
                    "entity_type": "station_queue",
                    "station_id": self.station_id,
                    "station": self.station_name,
                    "payload": payload
                }
                print(json.dumps(event), file=sys.stdout, flush=True)
                
                self.boarding_count += 1
                # Schedule next boarding if more passengers
                if self.passenger_queue:
                    self.hold_in("BOARDING", 0.025)
                else:
                    self.boarding = False
                    self.hold_in("IDLE", float('inf'))
            else:
                # No more passengers to board
                self.boarding = False
                self.hold_in("IDLE", float('inf'))
        else:
            self.hold_in("IDLE", float('inf'))
    
    def deltext(self, e):
        # Check if input is passenger generation
        if e.port == self.in_port:
            # Add to queue
            for value in e.values:
                self.passenger_queue.append(value)
            if not self.boarding:
                # If not boarding, no need to do anything now
                self.hold_in("IDLE", float('inf'))
        elif e.port == self.train_arrival_port:
            # Train arrived, start boarding
            self.boarding = True
            self.boarding_start_time = self.get_time()
            self.boarding_count = 0
            # Start boarding process
            if self.passenger_queue:
                self.hold_in("BOARDING", 0.025)
            else:
                self.hold_in("IDLE", float('inf'))
        else:
            self.hold_in("IDLE", float('inf'))
    
    def exit(self):
        pass

class TrainQueue(Atomic):
    def __init__(self, parent):
        super().__init__("train_queue")
        self.parent = parent
        self.passenger_queue = deque()
        self.alighting = False
        self.alighting_start_time = 0.0
        self.alighting_count = 0
        
        # Ports
        self.in_port = Port(object, "in_port")
        self.out_port = Port(object, "out_port")
        self.train_arrival_port = Port(object, "train_arrival_port")
        self.add_in_port(self.in_port)
        self.add_in_port(self.train_arrival_port)
        self.add_out_port(self.out_port)
        
        # Initialize
        self.hold_in("IDLE", float('inf'))
    
    def initialize(self):
        self.hold_in("IDLE", float('inf'))
    
    def lambdaf(self):
        # No output in this model
        pass
    
    def deltint(self):
        if self.alighting:
            # Process alighting
            if self.passenger_queue:
                # Alight next passenger
                passenger = self.passenger_queue.popleft()
                alighting_delay = 0.025 * self.alighting_count
                event_time = self.alighting_start_time + alighting_delay
                
                payload = {
                    "passenger_id": passenger["passenger_id"],
                    "passenger_num": passenger["passenger_num"],
                    "origin": passenger["origin"],
                    "destination": passenger["destination"]
                }
                
                event = {
                    "time": event_time,
                    "event": "passenger_exiting",
                    "entity_type": "train_queue",
                    "station_id": passenger["destination"],
                    "station": STATIONS[passenger["destination"]],
                    "payload": payload
                }
                print(json.dumps(event), file=sys.stdout, flush=True)
                
                self.alighting_count += 1
                # Schedule next alighting if more passengers
                if self.passenger_queue:
                    self.hold_in("ALIGHTING", 0.025)
                else:
                    self.alighting = False
                    self.hold_in("IDLE", float('inf'))
            else:
                # No more passengers to alight
                self.alighting = False
                self.hold_in("IDLE", float('inf'))
        else:
            self.hold_in("IDLE", float('inf'))
    
    def deltext(self, e):
        # Check if input is train arrival
        if e.port == self.train_arrival_port:
            # Train arrived, start alighting
            self.alighting = True
            self.alighting_start_time = self.get_time()
            self.alighting_count = 0
            # Start alighting process
            if self.passenger_queue:
                self.hold_in("ALIGHTING", 0.025)
            else:
                self.hold_in("IDLE", float('inf'))
        elif e.port == self.in_port:
            # Add passengers to train
            for value in e.values:
                self.passenger_queue.append(value)
            if not self.alighting:
                self.hold_in("IDLE", float('inf'))
        else:
            self.hold_in("IDLE", float('inf'))
    
    def exit(self):
        pass

class TrainScheduler(Atomic):
    def __init__(self, parent):
        super().__init__("train_scheduler")
        self.parent = parent
        self.current_station_index = 0
        self.current_station_id = 1
        self.current_direction = 0
        self.arrival_time = 0.0
        self.train_position = 0.0  # Fraction of distance between stations (0.0 to 1.0)
        
        # Ports
        self.out_port = Port(object, "out_port")
        self.passenger_boarding_port = Port(object, "passenger_boarding_port")
        self.passenger_exiting_port = Port(object, "passenger_exiting_port")
        self.add_out_port(self.out_port)
        self.add_in_port(self.passenger_boarding_port)
        self.add_in_port(self.passenger_exiting_port)
        
        # Initialize
        self.hold_in("INIT", 0)
    
    def initialize(self):
        self.arrival_time = 0.0
        # Initial train arrival at Bayview (station 1, direction 0)
        self.current_station_index = 0
        self.current_station_id = 1
        self.current_direction = 0
        
        payload = {
            "station": self.current_station_id,
            "direction": self.current_direction
        }
        
        event = {
            "time": self.arrival_time,
            "event": "train_arrival",
            "entity_type": "train",
            "station_id": self.current_station_id,
            "station": STATIONS[self.current_station_id],
            "payload": payload
        }
        print(json.dumps(event), file=sys.stdout, flush=True)
        
        # Schedule next arrival
        self.hold_in("WAITING", 225.0)
    
    def lambdaf(self):
        # No output in this model
        pass
    
    def deltint(self):
        # Move to next station
        self.current_station_index = (self.current_station_index + 1) % len(ROUTE)
        self.current_station_id, self.current_direction = ROUTE[self.current_station_index]
        
        self.arrival_time += 225.0
        
        payload = {
            "station": self.current_station_id,
            "direction": self.current_direction
        }
        
        event = {
            "time": self.arrival_time,
            "event": "train_arrival",
            "entity_type": "train",
            "station_id": self.current_station_id,
            "station": STATIONS[self.current_station_id],
            "payload": payload
        }
        print(json.dumps(event), file=sys.stdout, flush=True)
        
        # Schedule next arrival
        self.hold_in("WAITING", 225.0)
    
    def deltext(self, e):
        # No external transitions
        self.hold_in("WAITING", self.sigma)
    
    def exit(self):
        pass

class System(Coupled):
    def __init__(self, name, parent, simulate_time):
        super().__init__(name)
        self.parent = parent
        self.simulate_time = simulate_time
        
        # Create components
        self.train_scheduler = TrainScheduler(self)
        self.passenger_generators = [PassengerGenerator(i, self) for i in range(1, 6)]
        self.station_queues = [StationQueue(i, self) for i in range(1, 6)]
        self.train_queue = TrainQueue(self)
        
        # Add components
        self.add_component(self.train_scheduler)
        for pg in self.passenger_generators:
            self.add_component(pg)
        for sq in self.station_queues:
            self.add_component(sq)
        self.add_component(self.train_queue)
        
        # Define couplings
        # Passenger generators to station queues
        for i, pg in enumerate(self.passenger_generators):
            self.add_coupling(pg.out_port, self.station_queues[i].in_port)
        
        # Train scheduler to station queues
        for i, sq in enumerate(self.station_queues):
            self.add_coupling(self.train_scheduler.out_port, sq.train_arrival_port)
        
        # Station queues to train queue
        for i, sq in enumerate(self.station_queues):
            self.add_coupling(sq.out_port, self.train_queue.in_port)
        
        # Train scheduler to train queue
        self.add_coupling(self.train_scheduler.out_port, self.train_queue.train_arrival_port)
        
        # Train queue to station queues (for alighting passengers)
        self.add_coupling(self.train_queue.out_port, self.station_queues[0].in_port)  # This is a simplified approach
        self.add_coupling(self.train_queue.out_port, self.station_queues[1].in_port)
        self.add_coupling(self.train_queue.out_port, self.station_queues[2].in_port)
        self.add_coupling(self.train_queue.out_port, self.station_queues[3].in_port)
        self.add_coupling(self.train_queue.out_port, self.station_queues[4].in_port)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate_time", type=str, default="00:01:00:000")
    args = parser.parse_args()
    
    # Parse simulate_time
    parts = args.simulate_time.split(":")
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3])
    
    simulate_time = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
    
    # Create system
    root = System("system", None, simulate_time)
    
    # Create coordinator
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    
    # Run simulation
    coord.simulate_time(simulate_time)

if __name__ == "__main__":
    main()