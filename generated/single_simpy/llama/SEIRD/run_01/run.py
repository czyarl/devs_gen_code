```python
import argparse
import sys
import json
import logging
import random
import simpy
import math

# Set up logging
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def seird_model(env, test_name, mortality, infectivity_period, dt, incubation_period, total_population, initial_infective, transmission_rate, simulation_time):
    # Initialize compartments
    S = total_population - initial_infective
    E = 0
    I = initial_infective
    R = 0
    D = 0
    N = total_population
    time = 0.0

    while time < simulation_time:
        # Calculate new exposed
        new_exposed = (transmission_rate * S * I / N) * dt
        new_exposed = min(new_exposed, S)

        # Update S
        S -= new_exposed

        # Calculate new infective
        new_infective = (E / incubation_period) * dt
        new_infective = min(new_infective, E)

        # Update E
        E += new_exposed - new_infective

        # Update I
        new_deceased = (I / infectivity_period) * (mortality / 100) * dt
        new_recovered = (I / infectivity_period) * (1 - mortality / 100) * dt
        I += new_infective - new_deceased - new_recovered

        # Update R and D
        R += new_recovered
        D += new_deceased

        # Update time
        time += dt

        # Log progress
        logging.info(f'Time: {time:.2f}, S: {S:.2f}, E: {E:.2f}, I: {I:.2f}, R: {R:.2f}, D: {D:.2f}')

    # Output final state
    final_state = {
        "time": time,
        "susceptible": round(S, 2),
        "exposed": round(E, 2),
        "infective": round(I, 2),
        "recovered": round(R, 2),
        "deceased": round(D, 2)
    }
    print(json.dumps(final_state))

def main():
    parser = argparse.ArgumentParser(description='SEIRD Epidemic Compartmental Model Simulation')
    parser.add_argument('--test_name', type=str, required=True, help='Name of the test case being run')
    parser.add_argument('--mortality', type=float, default=10.0, help='Mortality rate as percentage (0-100)')
    parser.add_argument('--infectivity_period', type=float, default=14.0, help='Average days a person stays infectious')
    parser.add_argument('--dt', type=float, default=0.1, help='Time step for numerical integration in days')
    parser.add_argument('--incubation_period', type=float, default=5.0, help='Average days from exposure to becoming infectious')
    parser.add_argument('--total_population', type=int, default=1000, help='Total population size')
    parser.add_argument('--initial_infective', type=int, default=10, help='Initial number of infected individuals')
    parser.add_argument('--transmission_rate', type=float, default=2.5, help='Transmission rate (β) per day')
    parser.add_argument('--simulation_time', type=float, default=10.0, help='Total simulation time in days')

    args = parser.parse_args()

    seird_model(None, args.test_name, args.mortality, args.infectivity_period, args.dt, args.incubation_period, args.total_population, args.initial_infective, args.transmission_rate, args.simulation_time)

if __name__ == '__main__':
    main()
</python_code>
```