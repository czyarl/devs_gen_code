```python
import argparse
import sys
import json
import logging
import random
import collections
import time
import math

# Set up logging
logging.basicConfig(stream=sys.stderr, level=logging.INFO)

# Define constants
TIME_UNIT = 1.0

class Pallet:
    def __init__(self, pallet_id, generation_time, expiration_time):
        self.pallet_id = pallet_id
        self.generation_time = generation_time
        self.expiration_time = expiration_time

class Aircraft:
    def __init__(self, aircraft_id):
        self.aircraft_id = aircraft_id
        self.state = "idle"
        self.pallet = None
        self.current_time = 0.0

    def __str__(self):
        return f"Aircraft-{self.aircraft_id}"

class Facility:
    def __init__(self):
        self.pallet_id_counter = 0

    def generate_pallet(self, current_time):
        self.pallet_id_counter += 1
        pallet = Pallet(self.pallet_id_counter, current_time, current_time + pallet_expiration_time)
        print(json.dumps({"time": current_time, "entity": "facility", "event": "pallet_generated", "payload": {"pallet_id": self.pallet_id_counter, "expiration_time": pallet.expiration_time}}))
        return pallet

class LoadingQueue:
    def __init__(self):
        self.pallets = collections.deque()

    def add_pallet(self, pallet, current_time):
        self.pallets.append(pallet)
        print(json.dumps({"time": current_time, "entity": "queue", "event": "pallet_queued", "payload": {"pallet_id": pallet.pallet_id, "queue_size": len(self.pallets)}}))

    def remove_pallet(self, current_time):
        if self.pallets:
            pallet = self.pallets.popleft()
            return pallet
        return None

    def check_expiration(self, current_time):
        while self.pallets and self.pallets[0].expiration_time <= current_time:
            pallet = self.pallets.popleft()
            print(json.dumps({"time": current_time, "entity": "queue", "event": "pallet_expired", "payload": {"pallet_id": pallet.pallet_id, "total_expired": len(self.pallets)}}))
            return pallet
        return None

class Coordinator:
    def __init__(self):
        pass

    def assign_pallet(self, aircraft, pallet, current_time):
        aircraft.pallet = pallet
        print(json.dumps({"time": current_time, "entity": "coordinator", "event": "assignment_created", "payload": {"aircraft_id": aircraft.aircraft_id, "pallet_id": pallet.pallet_id}}))

class Destination:
    def __init__(self):
        pass

    def deliver_pallet(self, pallet, aircraft, current_time, latency):
        print(json.dumps({"time": current_time, "entity": "destination", "event": "pallet_delivered", "payload": {"pallet_id": pallet.pallet_id, "aircraft_id": aircraft.aircraft_id, "latency": latency}}))

def simulate(duration, num_aircraft, pallet_interval, pallet_expiration_time, flight_time, unload_time, return_time, maintenance_time):
    facility = Facility()
    loading_queue = LoadingQueue()
    coordinator = Coordinator()
    destination = Destination()
    aircraft_list = [Aircraft(i) for i in range(1, num_aircraft + 1)]

    current_time = 0.0
    last_pallet_generation = 0.0

    while current_time < duration:
        # Generate new pallet
        if current_time - last_pallet_generation >= pallet_interval:
            pallet = facility.generate_pallet(current_time)
            loading_queue.add_pallet(pallet, current_time)
            last_pallet_generation = current_time

        # Check pallet expiration in queue
        expired_pallet = loading_queue.check_expiration(current_time)
        if expired_pallet:
            loading_queue.pallets = collections.deque([p for p in loading_queue.pallets if p.pallet_id != expired_pallet.pallet_id])

        # Assign pallet to aircraft
        for aircraft in aircraft_list:
            if aircraft.state == "idle" and loading_queue.pallets:
                pallet = loading_queue.remove_pallet(current_time)
                coordinator.assign_pallet(aircraft, pallet, current_time)
                aircraft.state = "loading"
                aircraft.current_time = current_time
                print(json.dumps({"time": current_time, "entity": "aircraft", "event": "depart", "payload": {"aircraft_id": aircraft.aircraft_id, "pallet_id": pallet.pallet_id}}))
                aircraft.state = "in-flight"
                time_to_unload = current_time + flight_time + unload_time
                latency = time_to_unload - pallet.generation_time
                destination.deliver_pallet(pallet, aircraft, time_to_unload, latency)
                aircraft.state = "unloading"
                aircraft.current_time = time_to_unload
                aircraft.state = "returning"
                aircraft.current_time = time_to_unload + return_time
                aircraft.state = "maintenance"
                aircraft.current_time = aircraft.current_time + maintenance_time
                aircraft.state = "idle"
                aircraft.pallet = None

        current_time += 1.0

    print(json.dumps({"time": current_time, "entity": "simulator", "event": "simulation_end", "payload": {}}))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Airfreight Logistics Simulation')
    parser.add_argument('--duration', type=float, default=10000.0, help='Total simulation time')
    parser.add_argument('--num_aircraft', type=int, default=2, help='Number of aircraft')
    parser.add_argument('--pallet_interval', type=float, default=25.0, help='Time interval between pallet generations')
    parser.add_argument('--pallet_expiration_time', type=float, default=150.0, help='Pallet expiration time')
    parser.add_argument('--flight_time', type=float, default=30.0, help='Flight time')
    parser.add_argument('--unload_time', type=float, default=2.0, help='Unload time')
    parser.add_argument('--return_time', type=float, default=30.0, help='Return time')
    parser.add_argument('--maintenance_time', type=float, default=10.0, help='Maintenance time')

    args = parser.parse_args()

    global pallet_expiration_time
    pallet_expiration_time = args.pallet_expiration_time

    simulate(args.duration, args.num_aircraft, args.pallet_interval, args.pallet_expiration_time, args.flight_time, args.unload_time, args.return_time, args.maintenance_time)
</python_code>
```