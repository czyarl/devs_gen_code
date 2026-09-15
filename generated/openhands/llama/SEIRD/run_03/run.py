#!/usr/bin/env python3.10
import argparse
import sys
import json
import logging
from collections import defaultdict
import random
from simpy import Environment

# Set up logging
logging.basicConfig(stream=sys.stderr, level=logging.INFO)

# Define the SEIRD model
class SEIRDModel:
    def __init__(self, env, mortality, infectivity_period, dt, incubation_period, total_population, initial_infective, transmission_rate):
        self.env = env
        self.mortality = mortality / 100
        self.infectivity_period = infectivity_period
        self.dt = dt
        self.incubation_period = incubation_period
        self.total_population = total_population
        self.initial_infective = initial_infective
        self.transmission_rate = transmission_rate
        self.susceptible = total_population - initial_infective
        self.exposed = 0
        self.infective = initial_infective
        self.recovered = 0
        self.deceased = 0
        self.time = 0.0

    def simulate(self):
        while self.time < simulation_time:
            # Update SEIRD counts
            new_exposed = (self.transmission_rate * self.susceptible * self.infective / self.total_population) * self.dt
            new_exposed = min(new_exposed, self.susceptible)
            self.susceptible -= new_exposed
            self.exposed += new_exposed

            new_infective = (self.exposed / self.incubation_period) * self.dt
            new_infective = min(new_infective, self.exposed)
            self.exposed -= new_infective
            self.infective += new_infective

            new_deceased = (self.infective / self.infectivity_period) * (self.mortality) * self.dt
            new_recovered = (self.infective / self.infectivity_period) * (1 - self.mortality) * self.dt
            self.infective -= new_deceased + new_recovered
            self.recovered += new_recovered
            self.deceased += new_deceased

            self.time += self.dt
            yield self.env.timeout(self.dt)

        print(json.dumps({
            "time": self.time,
            "susceptible": self.susceptible,
            "exposed": self.exposed,
            "infective": self.infective,
            "recovered": self.recovered,
            "deceased": self.deceased
        }))

# Parse command line arguments
parser = argparse.ArgumentParser()
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

# Create and run the simulation
env = Environment()
model = SEIRDModel(env, args.mortality, args.infectivity_period, args.dt, args.incubation_period, args.total_population, args.initial_infective, args.transmission_rate)
env.process(model.simulate())

simulation_time = args.simulation_time
env.run(until=simulation_time)