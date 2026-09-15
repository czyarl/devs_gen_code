import argparse
import sys
import json
import logging
import collections
import random
import simpy
import xdevs

def main():
    parser = argparse.ArgumentParser(description='SEIRD Epidemic Compartmental Model')
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

    # Initialize compartments
    S = args.total_population - args.initial_infective
    E = 0
    I = args.initial_infective
    R = 0
    D = 0

    # Simulation
    time = 0.0
    while time < args.simulation_time:
        new_exposed = (args.transmission_rate * S * I / args.total_population) * args.dt
        new_exposed = min(new_exposed, S)
        S -= new_exposed
        E += new_exposed

        new_infective = (E / args.incubation_period) * args.dt
        new_infective = min(new_infective, E)
        E -= new_infective
        I += new_infective

        new_deceased = (I / args.infectivity_period) * (args.mortality / 100) * args.dt
        new_recovered = (I / args.infectivity_period) * (1 - args.mortality / 100) * args.dt
        I -= new_deceased + new_recovered
        R += new_recovered
        D += new_deceased

        time += args.dt

    # Output
    output = {
        'time': time,
        'susceptible': S,
        'exposed': E,
        'infective': I,
        'recovered': R,
        'deceased': D
    }
    print(json.dumps(output))

if __name__ == '__main__':
    main()
