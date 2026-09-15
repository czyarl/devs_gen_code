import argparse
import sys
import json
import logging
from collections import defaultdict
import random
import simpy

# Set up logging
logging.basicConfig(stream=sys.stderr, level=logging.INFO)

# Define SEIRD model
class SEIRD:
    def __init__(self, total_population, initial_infective, mortality, infectivity_period, incubation_period, transmission_rate, simulation_time, dt):
        self.total_population = total_population
        self.initial_infective = initial_infective
        self.mortality = mortality / 100.0
        self.infectivity_period = infectivity_period
        self.incubation_period = incubation_period
        self.transmission_rate = transmission_rate
        self.simulation_time = simulation_time
        self.dt = dt

        self.population = {
            'S': total_population - initial_infective,
            'E': 0,
            'I': initial_infective,
            'R': 0,
            'D': 0
        }

    def simulate(self):
        env = simpy.Environment()
        logging.info('Simulation started.')

        def update_population(env):
            while True:
                # S -> E
                new_exposed = self.transmission_rate * self.population['S'] * self.population['I'] / self.total_population * self.dt
                new_exposed = min(new_exposed, self.population['S'])
                self.population['S'] -= new_exposed
                self.population['E'] += new_exposed

                # E -> I
                new_infective = self.population['E'] / self.incubation_period * self.dt
                new_infective = min(new_infective, self.population['E'])
                self.population['E'] -= new_infective
                self.population['I'] += new_infective

                # I -> R
                new_recovered = self.population['I'] / self.infectivity_period * (1 - self.mortality) * self.dt
                self.population['I'] -= new_recovered
                self.population['R'] += new_recovered

                # I -> D
                new_deceased = self.population['I'] / self.infectivity_period * self.mortality * self.dt
                self.population['I'] -= new_deceased
                self.population['D'] += new_deceased

                yield env.timeout(self.dt)

        env.process(update_population(env))
        env.run(until=self.simulation_time)

        logging.info('Simulation finished.')
        return {
            'time': self.simulation_time,
            'susceptible': round(self.population['S'], 2),
            'exposed': round(self.population['E'], 2),
            'infective': round(self.population['I'], 2),
            'recovered': round(self.population['R'], 2),
            'deceased': round(self.population['D'], 2)
        }

def main():
    parser = argparse.ArgumentParser(description='SEIRD Simulation')
    parser.add_argument('--test_name', type=str, required=True)
    parser.add_argument('--mortality', type=float, default=10.0)
    parser.add_argument('--infectivity_period', type=float, default=14.0)
    parser.add_argument('--dt', type=float, default=0.1)
    parser.add_argument('--incubation_period', type=float, default=5.0)
    parser.add_argument('--total_population', type=int, default=1000)
    parser.add_argument('--initial_infective', type=int, default=10)
    parser.add_argument('--transmission_rate', type=float, default=2.5)
    parser.add_argument('--simulation_time', type=float, default=10.0)
    args = parser.parse_args()

    seird = SEIRD(args.total_population, args.initial_infective, args.mortality, args.infectivity_period, args.incubation_period, args.transmission_rate, args.simulation_time, args.dt)
    result = seird.simulate()
    print(json.dumps(result))

if __name__ == '__main__':
    main()