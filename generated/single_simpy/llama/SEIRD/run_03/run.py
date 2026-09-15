```python
import argparse
import json
import logging
import sys
import math

# Set up logging
logging.basicConfig(stream=sys.stderr, level=logging.INFO)

def parse_args():
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
    return parser.parse_args()

def seird_model(args):
    # Initialize compartments
    S = args.total_population - args.initial_infective
    E = 0.0
    I = args.initial_infective
    R = 0.0
    D = 0.0
    N = args.total_population

    # Time parameters
    dt = args.dt
    time = 0.0

    while time < args.simulation_time:
        # Calculate new exposed
        new_exposed = (args.transmission_rate * S * I / N) * dt
        new_exposed = min(new_exposed, S)

        # Update compartments
        S_new = S - new_exposed
        E_new = E + new_exposed

        # Calculate new infective
        new_infective = (E / args.incubation_period) * dt
        new_infective = min(new_infective, E)

        # Update compartments
        E_new = E_new - new_infective
        I_new = I + new_infective

        # Calculate new deceased and recovered
        new_deceased = (I / args.infectivity_period) * (args.mortality / 100) * dt
        new_recovered = (I / args.infectivity_period) * (1 - args.mortality / 100) * dt

        # Update compartments
        I_new = I_new - new_deceased - new_recovered
        R_new = R + new_recovered
        D_new = D + new_deceased

        # Update state
        S = S_new
        E = E_new
        I = I_new
        R = R_new
        D = D_new
        time += dt

    # Output final state
    output = {
        "time": round(time, 2),
        "susceptible": round(S, 2),
        "exposed": round(E, 2),
        "infective": round(I, 2),
        "recovered": round(R, 2),
        "deceased": round(D, 2)
    }
    print(json.dumps(output))

def main():
    args = parse_args()
    logging.info(f"Running simulation with args: {args}")
    seird_model(args)

if __name__ == "__main__":
    main()
</python_code>
```