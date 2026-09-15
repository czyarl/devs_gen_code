from xdevs.models import Atomic, Coupled, Port
import random
import time
import json
import sys
from devs_project.devs_utils.devs_context import get_current_time

# Set random seed as per requirements
random.seed(time.time_ns())

class Station(Atomic):
    def __init__(self, name: str, parent: Coupled | None, station_id: int, station_name: str, all_station_ids: list, gen_mean_min: float, gen_std_min: float, boarding_delay: float):
        super().__init__(name)
        self.parent = parent
        
        # Configuration parameters
        self.station_id = station_id
        self.station_name = station_name
        self.all_station_ids = all_station_ids
        self.gen_mean_min = gen_mean_min
        self.gen_std_min = gen_std_min
        self.boarding_delay = boarding_delay
        
        # Ports
        self.add_in_port(Port(dict, "train_arrival_in"))
        self.add_out_port(Port(dict, "passenger_boarded_out"))
        
        # Internal State
        self.queue = []  # List of passenger dicts
        self.passenger_num = 0  # Counter for generating passenger IDs
        self.next_gen_time = 0.5  # Initial generation time (t=0.5s)
        
        # Boarding State
        self.current_boarding_passenger = None
        
        # State restoration variables
        self._interrupted_gen_time = None

    def initialize(self):
        # Schedule the initial passenger generation at t=0.5s
        self.hold_in("GENERATING", self.next_gen_time)

    def _generate_passenger(self):
        """Creates a passenger and adds to queue."""
        current_time = get_current_time()
        
        # Determine Passenger ID and details
        if self.passenger_num == 0:
            # Initial passenger at t=0.5s
            p_id = 0
            p_num = 0
            possible_destinations = [sid for sid in self.all_station_ids if sid != self.station_id]
            destination = random.choice(possible_destinations)
        else:
            p_num = self.passenger_num
            possible_destinations = [sid for sid in self.all_station_ids if sid != self.station_id]
            destination = random.choice(possible_destinations)
            # ID = num * 100 + origin * 10 + dest
            p_id = p_num * 100 + self.station_id * 10 + destination

        passenger = {
            'passenger_id': p_id,
            'passenger_num': p_num,
            'origin': self.station_id,
            'destination': destination
        }
        
        self.queue.append(passenger)
        
        # Write to stdout (External IO)
        record = {
            'time': current_time,
            'event': 'passenger_generated',
            'entity_type': 'passenger_generator',
            'station_id': self.station_id,
            'station': self.station_name,
            'payload': passenger
        }
        print(json.dumps(record), flush=True)
        
        # Update counter
        self.passenger_num += 1
        
        # Schedule next generation
        # Normal Dist (Mean=5.0 min, Std=5.0 min) -> clamp [1, 9] min -> seconds -> round int
        interval_min = random.gauss(self.gen_mean_min, self.gen_std_min)
        interval_min = max(1.0, min(9.0, interval_min))
        interval_sec = round(interval_min * 60.0)
        
        self.next_gen_time = interval_sec

    def deltext(self, e):
        # 1. Calculate remaining time for current phase if active
        remaining_time = 0.0
        was_active = (self.phase != "IDLE")
        if was_active:
            remaining_time = max(0.0, self.ta() - e)
            
        # 2. Check for train arrival
        train_arrived = False
        for packet in self.input["train_arrival_in"].values:
            if packet['station'] == self.station_id:
                train_arrived = True
                break
        
        if train_arrived:
            if self.queue:
                # Start boarding
                self.current_boarding_passenger = self.queue.pop(0)
                self.hold_in("BOARDING", self.boarding_delay)
                
                # Save the state we interrupted
                if self.phase == "GENERATING":
                    self._interrupted_gen_time = remaining_time
                else:
                    self._interrupted_gen_time = None
            else:
                # Train arrived but queue empty.
                # Just stay in current state or passivate?
                # If we were generating, continue generating.
                if was_active:
                    self.hold_in(self.phase, remaining_time)
                else:
                    self.passivate("IDLE")
        else:
            # No train arrival (or wrong station)
            if was_active:
                self.hold_in(self.phase, remaining_time)

    def deltint(self):
        if self.phase == "GENERATING":
            self._generate_passenger()
            # Schedule next generation
            self.hold_in("GENERATING", self.next_gen_time)
            
        elif self.phase == "BOARDING":
            # Boarding event complete for one passenger
            # Logic to finish boarding and start next
            if self.queue:
                self.current_boarding_passenger = self.queue.pop(0)
                self.hold_in("BOARDING", self.boarding_delay)
            else:
                self.current_boarding_passenger = None
                # If we have a pending generation (interrupted), resume it?
                if self._interrupted_gen_time is not None:
                    self.hold_in("GENERATING", self._interrupted_gen_time)
                    self._interrupted_gen_time = None
                else:
                    self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "BOARDING":
            # Emit passenger data via 'passenger_boarded_out'
            # This happens when the timer expires, i.e., at the moment of boarding.
            if self.current_boarding_passenger:
                self.output["passenger_boarded_out"].add(self.current_boarding_passenger)
                
                # Write to stdout (External IO) - must happen at the same time as emission
                # Note: In DEVS, lambdaf is for outputs. deltint is for state changes.
                # The requirement asks to write 'passenger_boarding' event to stdout.
                # Since this is an "Independent Boundary Effect", we do it here.
                current_time = get_current_time()
                record = {
                    'time': current_time,
                    'event': 'passenger_boarding',
                    'entity_type': 'station_queue',
                    'station_id': self.station_id,
                    'station': self.station_name,
                    'payload': self.current_boarding_passenger
                }
                print(json.dumps(record), flush=True)

    def exit(self):
        pass