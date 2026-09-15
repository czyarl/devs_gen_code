import argparse
import json
import logging
import sys
from simpy import Environment

def seird_model(env, total_population, initial_infective, transmission_rate, incubation_period, infectivity_period, mortality):
    # Initialize compartments
    susceptible = total_population - initial_infective
    exposed = 0
    infective = initial_infective
    recovered = 0
    deceased = 0
    time = 0.0
    dt = 0.1

    while time < 10.0:  # Simulation time
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
        recovered += new_recovered
        deceased += new_deceased
        infective -= new_recovered + new_deceased

        time += dt

    # Print final state in JSONL format
    print(json.dumps({
        "time": time,
        "susceptible": round(susceptible, 2),
        "exposed": round(exposed, 2),
        "infective": round(infective, 2),
        "recovered": round(recovered, 2),
        "deceased": round(deceased, 2)
    }))