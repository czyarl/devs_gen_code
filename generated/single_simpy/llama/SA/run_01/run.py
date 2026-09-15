import argparse
import json
import logging
import random
import simpy
import sys
import time
from collections import defaultdict

# Configure logging
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Constants
TIME_UNIT = 1.0  # seconds

class Pallet:
    def __init__(self, pallet_id, generation_time, expiration_time):
        self.pallet_id = pallet_id
        self.generation_time = generation_time
        self.expiration_time = expiration_time

class Aircraft:
    def __init__(self, aircraft_id):
        self.aircraft_id = aircraft_id
        self.state = 'idle'
        self.pallet = None

class Facility:
    def __init__(self, env, pallet_interval, pallet_id_generator):
        self.env = env
        self.pallet_interval = pallet_interval
        self.pallet_id_generator = pallet_id_generator
        self.log = lambda time, event, payload: print(json.dumps({"time": time, "entity": "facility", "event": event, "payload": payload}))

    def run(self):
        pallet_id = next(self.pallet_id_generator)
        generation_time = self.env.now
        expiration_time = generation_time + pallet_expiration_time
        pallet = Pallet(pallet_id, generation_time, expiration_time)
        self.log(self.env.now, 'pallet_generated', {"pallet_id": pallet_id, "expiration_time": expiration_time})
        loading_queue.append(pallet)
        self.env.process(self.generate_pallet())

    def generate_pallet(self):
        while True:
            yield self.env.timeout(pallet_interval)
            pallet_id = next(self.pallet_id_generator)
            generation_time = self.env.now
            expiration_time = generation_time + pallet_expiration_time
            pallet = Pallet(pallet_id, generation_time, expiration_time)
            self.log(self.env.now, 'pallet_generated', {"pallet_id": pallet_id, "expiration_time": expiration_time})
            loading_queue.append(pallet)

class LoadingQueue:
    def __init__(self, env):
        self.env = env
        self.queue = []
        self.expired_pallets = 0
        self.log = lambda time, event, payload: print(json.dumps({"time": time, "entity": "queue", "event": event, "payload": payload}))

    def append(self, pallet):
        self.queue.append(pallet)
        self.log(self.env.now, 'pallet_queued', {"pallet_id": pallet.pallet_id, "queue_size": len(self.queue)})

    def check_expiration(self):
        while self.queue:
            pallet = self.queue[0]
            if self.env.now >= pallet.expiration_time:
                self.queue.pop(0)
                self.expired_pallets += 1
                self.log(self.env.now, 'pallet_expired', {"pallet_id": pallet.pallet_id, "total_expired": self.expired_pallets})
            else:
                break

class Coordinator:
    def __init__(self, env, num_aircraft):
        self.env = env
        self.num_aircraft = num_aircraft
        self.aircrafts = [Aircraft(i) for i in range(num_aircraft)]
        self.log = lambda time, event, payload: print(json.dumps({"time": time, "entity": "coordinator", "event": event, "payload": payload}))

    def assign_pallet(self):
        while True:
            yield self.env.timeout(0.1)
            available_aircraft = [aircraft for aircraft in self.aircrafts if aircraft.state == 'idle' and aircraft.pallet is None]
            if available_aircraft and loading_queue.queue:
                aircraft = random.choice(available_aircraft)
                pallet = loading_queue.queue.pop(0)
                aircraft.pallet = pallet
                aircraft.state = 'loading'
                self.log(self.env.now, 'assignment_created', {"aircraft_id": aircraft.aircraft_id, "pallet_id": pallet.pallet_id})
                self.env.process(self.handle_aircraft(aircraft))

    def handle_aircraft(self, aircraft):
        aircraft.state = 'loaded'
        self.log(self.env.now, 'depart', {"aircraft_id": aircraft.aircraft_id, "pallet_id": aircraft.pallet.pallet_id})
        yield self.env.timeout(flight_time)
        aircraft.state = 'unloading'
        yield self.env.timeout(unload_time)
        self.log(self.env.now, 'pallet_delivered', {"pallet_id": aircraft.pallet.pallet_id, "aircraft_id": aircraft.aircraft_id, "latency": self.env.now - aircraft.pallet.generation_time})
        aircraft.state = 'returning'
        yield self.env.timeout(return_time)
        aircraft.state = 'maintaining'
        self.log(self.env.now, 'return', {"aircraft_id": aircraft.aircraft_id})
        yield self.env.timeout(maintenance_time)
        aircraft.state = 'idle'
        aircraft.pallet = None
        self.log(self.env.now, 'maintenance_end', {"aircraft_id": aircraft.aircraft_id})

def main():
    global pallet_interval, num_aircraft, pallet_expiration_time, flight_time, unload_time, return_time, maintenance_time, loading_queue
    parser = argparse.ArgumentParser()
    parser.add_argument('--duration', type=float, default=10000.0)
    parser.add_argument('--num_aircraft', type=int, default=2)
    parser.add_argument('--pallet_interval', type=float, default=25.0)
    parser.add_argument('--pallet_expiration_time', type=float, default=150.0)
    parser.add_argument('--flight_time', type=float, default=30.0)
    parser.add_argument('--unload_time', type=float, default=2.0)
    parser.add_argument('--return_time', type=float, default=30.0)
    parser.add_argument('--maintenance_time', type=float, default=10.0)
    args = parser.parse_args()

    global duration, pallet_interval, num_aircraft, pallet_expiration_time, flight_time, unload_time, return_time, maintenance_time
    duration = args.duration
    pallet_interval = args.pallet_interval
    num_aircraft = args.num_aircraft
    pallet_expiration_time = args.pallet_expiration_time
    flight_time = args.flight_time
    unload_time = args.unload_time
    return_time = args.return_time
    maintenance_time = args.maintenance_time

    env = simpy.Environment()
    pallet_id_generator = iter(range(1000))
    facility = Facility(env, pallet_interval, pallet_id_generator)
    loading_queue = LoadingQueue(env)
    coordinator = Coordinator(env, num_aircraft)

    env.process(facility.run())
    env.process(coordinator.assign_pallet())

    start_time = time.time()
    while env.now < duration and time.time() - start_time < 10:
        env.step()
    logging.info(f"Simulation ended at time {env.now}")

if __name__ == "__main__":
    main()