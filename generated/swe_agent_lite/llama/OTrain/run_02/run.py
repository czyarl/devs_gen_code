import argparse
import sys
import json
import logging
import collections
import random
import simpy
import xdevs

def main():
    parser = argparse.ArgumentParser(description='O-Train Light Rail Simulation')
    parser.add_argument('--simulate_time', type=str, default='00:01:00:000', help='Simulation duration in HH:MM:SS:mmm')
    args = parser.parse_args()

    # Initialize logging
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)

    # Initialize random seed
    random.seed(time.time_ns())

    # Simulation environment
    env = simpy.Environment()

    # Stations configuration
    stations = {
        1: 'Bayview',
        2: 'Carling',
        3: 'Carleton',
        4: 'Confed',
        5: 'Greenboro'
    }

    # Train route configuration
    train_route = [(1, 0), (2, 0), (3, 0), (4, 0), (5, 1), (4, 1), (3, 1), (2, 1), (1, 0)]

    # Passenger generation
    def generate_passengers(env, station_id):
        passenger_num = 0
        while True:
            # Generate passenger at t=0.5 seconds
            if env.now == 0.5:
                passenger_id = 0
                origin = station_id
                destination = random.choice([s for s in stations if s != station_id])
                print(json.dumps({
                    'time': env.now,
                    'event': 'passenger_generated',
                    'entity_type': 'passenger_generator',
                    'station_id': station_id,
                    'station': stations[station_id],
                    'payload': {
                        'passenger_id': passenger_id,
                        'passenger_num': passenger_num,
                        'origin': origin,
                        'destination': destination
                    }
                }))
            # Generate passengers at random intervals
            interval = max(1, min(9, random.gauss(5, 5))) * 60
            yield env.timeout(interval)
            passenger_id = passenger_num * 100 + station_id * 10 + random.choice([s for s in stations if s != station_id])
            print(json.dumps({
                'time': env.now,
                'event': 'passenger_generated',
                'entity_type': 'passenger_generator',
                'station_id': station_id,
                'station': stations[station_id],
                'payload': {
                    'passenger_id': passenger_id,
                    'passenger_num': passenger_num,
                    'origin': station_id,
                    'destination': random.choice([s for s in stations if s != station_id])
                }
            }))
            passenger_num += 1

    # Train operations
    def train_operations(env, train_route):
        current_station_index = 0
        while True:
            current_station_id, direction = train_route[current_station_index]
            print(json.dumps({
                'time': env.now,
                'event': 'train_arrival',
                'entity_type': 'train',
                'station_id': current_station_id,
                'station': stations[current_station_id],
                'payload': {
                    'station': current_station_id,
                    'direction': direction
                }
            }))
            # Move to next station
            current_station_index = (current_station_index + 1) % len(train_route)
            yield env.timeout(225)

    # Start simulation
    env.process(train_operations(env, train_route))
    for station_id in stations:
        env.process(generate_passengers(env, station_id))

    try:
        simulate_time = args.simulate_time
        hours, minutes, seconds, milliseconds = map(int, simulate_time.split(':'))
        total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
        env.run(until=total_seconds)
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()