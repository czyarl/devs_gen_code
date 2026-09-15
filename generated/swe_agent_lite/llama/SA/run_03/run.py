import argparse
import sys
import json
import logging
import collections
import random
import xdevs

def main():
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

    # Initialize simulation environment
    env = xdevs.Environment()

    # Create facility, loading queue, fleet coordinator, aircraft, and destination
    facility = Facility(env, args.pallet_interval, args.pallet_expiration_time)
    loading_queue = LoadingQueue(env, args.pallet_expiration_time)
    coordinator = FleetCoordinator(env, loading_queue, args.num_aircraft)
    aircraft_list = [Aircraft(env, i, args.flight_time, args.unload_time, args.return_time, args.maintenance_time) for i in range(args.num_aircraft)]
    destination = Destination(env)

    # Connect components
    facility.loading_queue = loading_queue
    loading_queue.coordinator = coordinator
    coordinator.aircraft_list = aircraft_list
    coordinator.loading_queue = loading_queue
    coordinator.destination = destination
    destination.coordinator = coordinator

    # Start simulation
    env.run(until=args.duration)

if __name__ == '__main__':
    main()