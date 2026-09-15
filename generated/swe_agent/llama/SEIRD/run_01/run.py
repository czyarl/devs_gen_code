import argparse
import sys
import json
import logging
import collections
import random
import simpy

import argparse
import sys
import json
import logging
import collections
import random
import simpy
from simpy import Environment

def seird_model(env, total_population, initial_infective, transmission_rate, incubation_period, infectivity_period, mortality):
    # Initialize compartments
    susceptible = total_population - initial_infective
    exposed = 0
    infective = initial_infective
    recovered = 0
    deceased = 0

    # Simulation time
    simulation_time = 10.0
    time = 0.0
    dt = 0.1

    while time < simulation_time:
        # Calculate new exposed
        new_exposed = (transmission_rate * susceptible * infective / total_population) * dt
        new_exposed = min(new_exposed, susceptible)
        susceptible -= new_exposed
        exposed += new_exposed

        # Calculate new infective
        new_infective = (exposed / incubation_period) * dt
        new_infective = min(new_infective, exposed)
        exposed -= new_infective
        infective += new_infective

        # Calculate new recovered and deceased
        new_recovered = (infective / infectivity_period) * (1 - mortality / 100) * dt
        new_deceased = (infective / infectivity_period) * (mortality / 100) * dt
        infective -= new_recovered + new_deceased
        recovered += new_recovered
        deceased += new_deceased

        # Update time
        time += dt

    # Print final state
    return json.dumps({
        "time": time,
        "susceptible": round(susceptible, 2),
        "exposed": round(exposed, 2),
        "infective": round(infective, 2),
        "recovered": round(recovered, 2),
        "deceased": round(deceased, 2)
    })
def main():
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

    final_state = seird_model(None, args.total_population, args.initial_infective, args.transmission_rate, args.incubation_period, args.infectivity_period, args.mortality)
    print(final_state)

if __name__ == '__main__':
    main()