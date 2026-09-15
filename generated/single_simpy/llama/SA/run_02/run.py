import argparse
import json
import logging
import random
import sys
import simpy

# Configure logging
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(message)s')

# Define constants and defaults
DEFAULT_DURATION = 10000.0
DEFAULT_NUM_AIRCRAFT = 2
DEFAULT_PALLET_INTERVAL = 25.0
DEFAULT_PALLET_EXPIRATION_TIME = 150.0
DEFAULT_FLIGHT_TIME = 30.0
DEFAULT_UNLOAD_TIME = 2.0
DEFAULT_RETURN_TIME = 30.0
DEFAULT_MAINTENANCE_TIME = 10.0

# Define event types
EVENT_TYPES = {
    'pallet_generated': 'facility',
    'pallet_queued': 'queue',
    'pallet_expired': 'queue',
    'assignment_created': 'coordinator',
    'depart': 'aircraft',
    'return': 'aircraft',
    'maintenance_start': 'aircraft',
    'maintenance_end': 'aircraft',
    'pallet_delivered': 'destination'
}

class Pallet:
    def __init__(self, pallet_id, expiration_time):
        self.pallet_id = pallet_id
        self.expiration_time = expiration_time
        self.generation_time = None

class Aircraft:
    def __init__(self, aircraft_id):
        self.aircraft_id = aircraft_id
        self.state = 'idle'
        self.pallet = None

class Simulation:
    def __init__(self, env, args):
        self.env = env
        self.args = args
        self.facility = simpy.Resource(env)
        self.queue = simpy.Store(env)
        self.coordinator = simpy.Resource(env)
        self.aircrafts = [Aircraft(i) for i in range(args.num_aircraft)]
        self.destination = simpy.Resource(env)
        self.pallet_id = 0
        self.total_expired = 0
        self.pallet_gen_time = {}

        env.process(self.generate_pallets())
        env.process(self.monitor_queue())
        env.process(self.coordinate_assignments())
        env.process(self.aircraft_operations())

    def generate_pallets(self):
        while True:
            pallet_id = self.pallet_id
            self.pallet_id += 1
            expiration_time = self.env.now + self.args.pallet_expiration_time
            pallet = Pallet(pallet_id, expiration_time)
            pallet.generation_time = self.env.now
            self.pallet_gen_time[pallet_id] = pallet.generation_time
            self.queue.put(pallet)
            self.log_event('pallet_generated', 'facility', {'pallet_id': pallet_id, 'expiration_time': expiration_time})
            self.log_event('pallet_queued', 'queue', {'pallet_id': pallet_id, 'queue_size': len(self.queue.items)})
            yield self.env.timeout(self.args.pallet_interval)

    def monitor_queue(self):
        while True:
            if self.queue.items:
                pallet = self.queue.items[0]
                if self.env.now >= pallet.expiration_time:
                    self.queue.get()
                    self.total_expired += 1
                    self.log_event('pallet_expired', 'queue', {'pallet_id': pallet.pallet_id, 'total_expired': self.total_expired})
            yield self.env.timeout(1)

    def coordinate_assignments(self):
        while True:
            if self.queue.items and any(aircraft.state == 'idle' for aircraft in self.aircrafts):
                pallet = self.queue.get()
                aircraft = next(aircraft for aircraft in self.aircrafts if aircraft.state == 'idle')
                aircraft.pallet = pallet
                aircraft.state = 'loading'
                self.log_event('assignment_created', 'coordinator', {'aircraft_id': aircraft.aircraft_id, 'pallet_id': pallet.pallet_id})
                yield self.env.timeout(0)

                # Load, fly, unload, return, maintain
                aircraft.state = 'in-flight'
                self.log_event('depart', 'aircraft', {'aircraft_id': aircraft.aircraft_id, 'pallet_id': pallet.pallet_id})
                yield self.env.timeout(self.args.flight_time)

                aircraft.state = 'unloading'
                yield self.env.timeout(self.args.unload_time)
                self.log_event('pallet_delivered', 'destination', {'pallet_id': pallet.pallet_id, 'aircraft_id': aircraft.aircraft_id, 'latency': self.env.now - self.pallet_gen_time[pallet.pallet_id]})

                aircraft.state = 'returning'
                yield self.env.timeout(self.args.return_time)
                self.log_event('return', 'aircraft', {'aircraft_id': aircraft.aircraft_id})

                aircraft.state = 'maintaining'
                yield self.env.timeout(self.args.maintenance_time)
                self.log_event('maintenance_start', 'aircraft', {'aircraft_id': aircraft.aircraft_id})
                yield self.env.timeout(0)
                self.log_event('maintenance_end', 'aircraft', {'aircraft_id': aircraft.aircraft_id})
                aircraft.state = 'idle'
                aircraft.pallet = None

    def aircraft_operations(self):
        pass

    def log_event(self, event, entity, payload):
        event_time = self.env.now
        event_log = {
            "time": event_time,
            "entity": entity,
            "event": event,
            "payload": payload
        }
        print(json.dumps(event_log))

def main():
    parser = argparse.ArgumentParser(description='Airfreight Logistics Simulation')
    parser.add_argument('--duration', type=float, default=DEFAULT_DURATION)
    parser.add_argument('--num_aircraft', type=int, default=DEFAULT_NUM_AIRCRAFT)
    parser.add_argument('--pallet_interval', type=float, default=DEFAULT_PALLET_INTERVAL)
    parser.add_argument('--pallet_expiration_time', type=float, default=DEFAULT_PALLET_EXPIRATION_TIME)
    parser.add_argument('--flight_time', type=float, default=DEFAULT_FLIGHT_TIME)
    parser.add_argument('--unload_time', type=float, default=DEFAULT_UNLOAD_TIME)
    parser.add_argument('--return_time', type=float, default=DEFAULT_RETURN_TIME)
    parser.add_argument('--maintenance_time', type=float, default=DEFAULT_MAINTENANCE_TIME)
    args = parser.parse_args()

    env = simpy.Environment()
    sim = Simulation(env, args)
    env.run(until=args.duration)

if __name__ == "__main__":
    main()