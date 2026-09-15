import argparse
import json
import logging
import sys
from simpy import Environment

def seird_model(env, mortality, infectivity_period, dt, incubation_period, total_population, initial_infective, transmission_rate, simulation_time):
    # Initialize compartments
    S = total_population - initial_infective
    E = 0
    I = initial_infective
    R = 0
    D = 0
    time = 0.0

    while time < simulation_time:
        # Calculate new exposed
        new_exposed = (transmission_rate * S * I / total_population) * dt
        new_exposed = min(new_exposed, S)
        S -= new_exposed
        E += new_exposed

        # Calculate new infective
        new_infective = (E / incubation_period) * dt
        new_infective = min(new_infective, E)
        E -= new_infective
        I += new_infective

        # Calculate new deceased and recovered
        new_deceased = (I / infectivity_period) * (mortality / 100) * dt
        new_recovered = (I / infectivity_period) * (1 - mortality / 100) * dt
        I -= new_deceased + new_recovered
        R += new_recovered
        D += new_deceased

        time += dt

    # Output in JSONL format
    print(json.dumps({
        "time": time,
        "susceptible": round(S, 2),
        "exposed": round(E, 2),
        "infective": round(I, 2),
        "recovered": round(R, 2),
        "deceased": round(D, 2)
    }))

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

    env = Environment()
    seird_model(env, args.mortality, args.infectivity_period, args.dt, args.incubation_period, args.total_population, args.initial_infective, args.transmission_rate, args.simulation_time)

if __name__ == "__main__":
    main()