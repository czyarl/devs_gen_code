import argparse
import sys
import json
import random
import time
import logging
from collections import deque

# xdevs imports
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# --- Constants & Configuration ---
STATIONS = {
    1: "Bayview",
    2: "Carling",
    3: "Carleton",
    4: "Confed",
    5: "Greenboro"
}

# Route logic: (Station ID, Direction)
# 0 = Southbound (1->2->3->4->5)
# 1 = Northbound (5->4->3->2->1)
# Sequence defined in prompt: Bayview(1,0) -> Carling(2,0) -> Carleton(3,0) -> Confed(4,0) -> Greenboro(5,1) -> Confed(4,1) -> Carleton(3,1) -> Carling(2,1) -> Bayview(1,0)
ROUTE_SEQUENCE = [
    (1, 0), (2, 0), (3, 0), (4, 0), (5, 1),
    (4, 1), (3, 1), (2, 1), (1, 0)
]

TRAVEL_TIME = 225.0  # seconds
BOARDING_TIME = 0.025 # seconds per passenger
ALIGHTING_TIME = 0.025 # seconds per passenger
DWELL_TIME = 30.0 # Assumed dwell time for boarding/alighting window

# --- Helper Functions ---
def get_next_station_index(current_index):
    return (current_index + 1) % len(ROUTE_SEQUENCE)

def get_station_name(station_id):
    return STATIONS.get(station_id, "Unknown")

def print_event(time, event_type, entity_type, station_id, payload):
    data = {
        "time": round(time, 3),
        "event": event_type,
        "entity_type": entity_type,
        "station_id": station_id,
        "station": get_station_name(station_id),
        "payload": payload
    }
    print(json.dumps(data), file=sys.stdout, flush=True)

# --- Atomic Models ---

class PassengerGenerator(Atomic):
    def __init__(self, name: str, parent: Coupled | None, station_id: int):
        super().__init__(name)
        self.parent = parent
        self.station_id = station_id
        
        # Output ports
        self.out_passenger = Port(dict, "out_passenger")
        self.out_log = Port(dict, "out_log")
        
        self.add_out_port(self.out_passenger)
        self.add_out_port(self.out_log)
        
        self.passenger_num = 0
        self.initialized = False
        self.hold_in("idle", 0)

    def initialize(self):
        # Schedule the initial passenger at t=0.5
        self.hold_in("init_wait", 0.5)

    def lambdaf(self):
        payload = None
        if self.phase == "init_wait":
            # Create initial passenger (ID=0)
            # Destination must be different
            dest = 1 if self.station_id != 1 else 2
            payload = {
                "passenger_id": 0,
                "passenger_num": 0,
                "origin": self.station_id,
                "destination": dest
            }
            
        elif self.phase == "generating":
            # Create regular passenger
            possible_dests = [sid for sid in STATIONS.keys() if sid != self.station_id]
            dest = random.choice(possible_dests)
            
            passenger_id = self.passenger_num * 100 + self.station_id * 10 + dest
            
            payload = {
                "passenger_id": passenger_id,
                "passenger_num": self.passenger_num,
                "origin": self.station_id,
                "destination": dest
            }
        
        if payload:
            self.out_passenger.add(payload)
            self.out_log.add(payload)

    def deltint(self):
        if self.phase == "init_wait":
            self.initialized = True
            self.passenger_num = 1
            self.schedule_next_generation()
            
        elif self.phase == "generating":
            self.passenger_num += 1
            self.schedule_next_generation()

    def deltext(self, e):
        pass

    def schedule_next_generation(self):
        mean_min = 5.0
        std_min = 5.0
        val_min = random.gauss(mean_min, std_min)
        val_min = max(1.0, min(9.0, val_min))
        val_sec = round(val_min * 60.0)
        self.hold_in("generating", val_sec)

    def exit(self):
        pass


class StationQueue(Atomic):
    def __init__(self, name: str, parent: Coupled | None, station_id: int):
        super().__init__(name)
        self.parent = parent
        self.station_id = station_id
        
        # Inputs
        self.in_passenger = Port(dict, "in_passenger")
        self.in_train_arrival = Port(dict, "in_train_arrival")
        
        # Outputs
        self.out_boarding = Port(dict, "out_boarding")
        
        self.add_in_port(self.in_passenger)
        self.add_in_port(self.in_train_arrival)
        self.add_out_port(self.out_boarding)
        
        self.queue = deque()
        self.boarding_queue = deque()
        self.hold_in("idle", float('inf'))

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.phase == "boarding":
            if self.boarding_queue:
                p = self.boarding_queue[0]
                self.out_boarding.add(p)

    def deltint(self):
        if self.phase == "boarding":
            if self.boarding_queue:
                self.boarding_queue.popleft()
            
            if self.boarding_queue:
                self.hold_in("boarding", BOARDING_TIME)
            else:
                self.hold_in("idle", float('inf'))
        else:
            self.hold_in("idle", float('inf'))

    def deltext(self, e):
        # 1. New Passenger Arrives
        for p in self.in_passenger.values:
            if p["origin"] == self.station_id:
                self.queue.append(p)
        
        # 2. Train Arrives
        for _ in self.in_train_arrival.values:
            while self.queue:
                self.boarding_queue.append(self.queue.popleft())
            
            if self.boarding_queue:
                self.hold_in("boarding", BOARDING_TIME)
            else:
                self.hold_in("idle", float('inf'))

    def exit(self):
        pass


class Train(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Inputs
        self.in_boarding = Port(dict, "in_boarding")
        
        # Outputs
        self.out_arrival = Port(dict, "out_arrival")
        self.out_exiting = Port(dict, "out_exiting")
        
        self.add_in_port(self.in_boarding)
        self.add_out_port(self.out_arrival)
        self.add_out_port(self.out_exiting)
        
        self.route_index = 0
        self.passengers = []
        self.alighting_queue = deque()
        self.current_station_id = None
        
        self.hold_in("arrived", 0)

    def initialize(self):
        self.hold_in("arrived", 0)

    def lambdaf(self):
        if self.phase == "arrived":
            station_id, direction = ROUTE_SEQUENCE[self.route_index]
            payload = {
                "station": station_id,
                "direction": direction
            }
            self.out_arrival.add(payload)
            
        elif self.phase == "alighting":
            if self.alighting_queue:
                p = self.alighting_queue[0]
                self.out_exiting.add(p)

    def deltint(self):
        if self.phase == "arrived":
            station_id, _ = ROUTE_SEQUENCE[self.route_index]
            self.current_station_id = station_id
            
            # Filter alighting passengers
            to_alight = [p for p in self.passengers if p["destination"] == station_id]
            self.passengers = [p for p in self.passengers if p["destination"] != station_id]
            self.alighting_queue = deque(to_alight)
            
            if self.alighting_queue:
                self.hold_in("alighting", ALIGHTING_TIME)
            else:
                self.hold_in("boarding", DWELL_TIME)
                
        elif self.phase == "alighting":
            if self.alighting_queue:
                self.alighting_queue.popleft()
            
            if self.alighting_queue:
                self.hold_in("alighting", ALIGHTING_TIME)
            else:
                self.hold_in("boarding", DWELL_TIME)
                
        elif self.phase == "boarding":
            self.route_index = get_next_station_index(self.route_index)
            self.hold_in("traveling", TRAVEL_TIME)
            
        elif self.phase == "traveling":
            self.hold_in("arrived", 0)

    def deltext(self, e):
        if self.phase == "boarding":
            for p in self.in_boarding.values:
                self.passengers.append(p)

    def exit(self):
        pass


class Logger(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        self.in_generated = Port(dict, "in_generated")
        self.in_arrival = Port(dict, "in_arrival")
        self.in_boarding = Port(dict, "in_boarding")
        self.in_exiting = Port(dict, "in_exiting")
        
        self.add_in_port(self.in_generated)
        self.add_in_port(self.in_arrival)
        self.add_in_port(self.in_boarding)
        self.add_in_port(self.in_exiting)
        
        self.hold_in("active", float('inf'))

    def initialize(self):
        self.hold_in("active", float('inf'))

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        current_time = self.clock.get_time()
        
        for p in self.in_generated.values:
            print_event(
                time=current_time,
                event_type="passenger_generated",
                entity_type="passenger_generator",
                station_id=p["origin"],
                payload=p
            )
            
        for p in self.in_arrival.values:
            print_event(
                time=current_time,
                event_type="train_arrival",
                entity_type="train",
                station_id=p["station"],
                payload=p
            )
            
        for p in self.in_boarding.values:
            print_event(
                time=current_time,
                event_type="passenger_boarding",
                entity_type="station_queue",
                station_id=p["origin"],
                payload=p
            )
            
        for p in self.in_exiting.values:
            print_event(
                time=current_time,
                event_type="passenger_exiting",
                entity_type="train_queue",
                station_id=p["destination"],
                payload=p
            )

    def exit(self):
        pass


class OTrainSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Components
        self.train = Train(name="train", parent=self)
        self.add_component(self.train)
        
        self.logger = Logger(name="logger", parent=self)
        self.add_component(self.logger)
        
        self.generators = []
        self.queues = []
        
        for sid in STATIONS.keys():
            gen = PassengerGenerator(name=f"gen_{sid}", parent=self, station_id=sid)
            queue = StationQueue(name=f"queue_{sid}", parent=self, station_id=sid)
            
            self.generators.append(gen)
            self.queues.append(queue)
            
            self.add_component(gen)
            self.add_component(queue)
            
            # Couplings
            self.add_coupling(gen.out_passenger, queue.in_passenger)
            self.add_coupling(gen.out_log, self.logger.in_generated)
            
            self.add_coupling(self.train.out_arrival, queue.in_train_arrival)
            self.add_coupling(queue.out_boarding, self.train.in_boarding)
            self.add_coupling(queue.out_boarding, self.logger.in_boarding)
            
        # Train to Logger
        self.add_coupling(self.train.out_arrival, self.logger.in_arrival)
        self.add_coupling(self.train.out_exiting, self.logger.in_exiting)

def parse_time(time_str: str) -> float:
    parts = time_str.split(':')
    h = int(parts[0])
    m = int(parts[1])
    s_ms = parts[2].split('.')
    s = int(s_ms[0])
    ms = int(s_ms[1]) if len(s_ms) > 1 else 0
    return h * 3600 + m * 60 + s + ms / 1000.0

def main():
    parser = argparse.ArgumentParser(description="O-Train Light Rail Simulation")
    parser.add_argument("--simulate_time", type=str, default="00:01:00:000", help="Simulation duration in HH:MM:SS:mmm")
    args = parser.parse_args()

    # Set seed
    seed = time.time_ns()
    random.seed(seed)
    
    # Log seed to stderr
    print(f"Simulation started with seed: {seed}", file=sys.stderr)

    # Parse time
    sim_duration = parse_time(args.simulate_time)
    
    # Build Model
    root = OTrainSystem(name="o_train_system", parent=None)
    
    # Setup Coordinator
    coord = Coordinator(root, clock=SimulationClock(0))
    
    # Run
    coord.initialize()
    coord.simulate_time(sim_duration)
    
    print("Simulation finished.", file=sys.stderr)

if __name__ == "__main__":
    main()