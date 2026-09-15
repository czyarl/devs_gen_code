import argparse
import json
import logging
import random
import sys
from simpy import Environment, Resource

# Define constants and defaults for arguments
DEFAULT_DURATION = 10000.0
DEFAULT_NUM_AIRCRAFT = 2
DEFAULT_PALLET_INTERVAL = 25.0
DEFAULT_PALLET_EXPIRATION_TIME = 150.0
DEFAULT_FLIGHT_TIME = 30.0
DEFAULT_UNLOAD_TIME = 2.0
DEFAULT_RETURN_TIME = 30.0
DEFAULT_MAINTENANCE_TIME = 10.0

# Event types
EVENT_TYPES = {
    "pallet_generated": "facility",
    "pallet_queued": "queue",
    "pallet_expired": "queue",
    "assignment_created": "coordinator",
    "depart": "aircraft",
    "return": "aircraft",
    "maintenance_start": "aircraft",
    "maintenance_end": "aircraft",
    "pallet_delivered": "destination"
}

class Pallet:
    def __init__(self, pallet_id, expiration_time):
        self.pallet_id = pallet_id
        self.expiration_time = expiration_time

class Aircraft:
    def __init__(self, env, aircraft_id, flight_time, unload_time, return_time, maintenance_time):
        self.env = env
        self.aircraft_id = aircraft_id
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.state = "idle"

    def process(self):
        while True:
            # Simulate aircraft states
            if self.state == "idle":
                yield self.env.timeout(1)
            # Add more states and transitions as needed

def facility(env, pallet_interval, pallet_expiration_time):
    pallet_id = 0
    while True:
        pallet = Pallet(pallet_id, env.now + pallet_expiration_time)
        print(json.dumps({"time": env.now, "entity": "facility", "event": "pallet_generated", "payload": {"pallet_id": pallet.pallet_id, "expiration_time": pallet.expiration_time}}))
        pallet_id += 1
        yield env.timeout(pallet_interval)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION)
    parser.add_argument("--num_aircraft", type=int, default=DEFAULT_NUM_AIRCRAFT)
    parser.add_argument("--pallet_interval", type=float, default=DEFAULT_PALLET_INTERVAL)
    parser.add_argument("--pallet_expiration_time", type=float, default=DEFAULT_PALLET_EXPIRATION_TIME)
    parser.add_argument("--flight_time", type=float, default=DEFAULT_FLIGHT_TIME)
    parser.add_argument("--unload_time", type=float, default=DEFAULT_UNLOAD_TIME)
    parser.add_argument("--return_time", type=float, default=DEFAULT_RETURN_TIME)
    parser.add_argument("--maintenance_time", type=float, default=DEFAULT_MAINTENANCE_TIME)
    args = parser.parse_args()

    env = Environment()
    env.process(facility(env, args.pallet_interval, args.pallet_expiration_time))

    for i in range(args.num_aircraft):
        aircraft = Aircraft(env, i, args.flight_time, args.unload_time, args.return_time, args.maintenance_time)
        env.process(aircraft.process())

    env.run(until=args.duration)

if __name__ == "__main__":
    main()