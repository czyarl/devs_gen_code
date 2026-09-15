import argparse
import sys
import json
import logging
import random
import simpy
import xdevs

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulate_time', default='00:01:00:000')
    args = parser.parse_args()

    # Initialize the simulation environment
    env = simpy.Environment()

    # Define the stations
    stations = ['Bayview', 'Carling', 'Carleton', 'Confed', 'Greenboro']

    # Define the train's route
    route = [0, 0, 0, 0, 1, 1, 1, 1]

    # Define the passenger generation process
    def passenger_generation(env, station):
        while True:
            # Generate a new passenger
            passenger_id = random.randint(0, 100)
            origin = station
            destination = random.choice([s for s in stations if s != stations[station]])
            print(json.dumps({
                'time': env.now,
                'event': 'passenger_generated',
                'entity_type': 'passenger_generator',
                'station_id': station + 1,
                'station': stations[station],
                'payload': {
                    'passenger_id': passenger_id,
                    'passenger_num': 0,
                    'origin': station + 1,
                    'destination': stations.index([s for s in stations if s != stations[station]][0]) + 1
                }
            }))
            # Wait for a random interval
            yield env.timeout(random.uniform(1, 9) * 60)

    # Start the passenger generation process for each station
    for i in range(len(stations)):
        env.process(passenger_generation(env, i))

    # Run the simulation
    env.run(until=10)

if __name__ == '__main__':
    main()

