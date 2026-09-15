python
import argparse
import sys
import json
import logging

# Set up logging
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def simulate_seird(
    test_name: str,
    mortality: float,
    infectivity_period: float,
    dt: float,
    incubation_period: float,
    total_population: int,
    initial_infective: int,
    transmission_rate: float,
    simulation_time: float
):
    # Initialize compartments
    susceptible = total_population - initial_infective
    exposed = 0.0
    infective = initial_infective
    recovered = 0.0
    deceased = 0.0

    time = 0.0
    results = []

    while time < simulation_time:
        # Calculate new exposed
        new_exposed = (transmission_rate * susceptible * infective / total_population) * dt
        new_exposed = min(new_exposed, susceptible)

        # Update susceptible and exposed
        susceptible -= new_exposed
        exposed += new_exposed

        # Calculate new infective
        new_infective = (exposed / incubation_period) * dt
        new_infective = min(new_infective, exposed)

        # Update exposed and infective
        exposed -= new_infective
        infective += new_infective

        # Calculate new deceased and recovered
        new_deceased = (infective / infectivity_period) * (mortality / 100) * dt
        new_recovered = (infective / infectivity_period) * (1 - mortality / 100) * dt

        # Update infective, recovered, and deceased
        infective -= new_deceased + new_recovered
        recovered += new_recovered
        deceased += new_deceased

        # Update time
        time += dt

    # Output final state
    final_state = {
        "time": simulation_time,
        "susceptible": round(susceptible, 2),
        "exposed": round(exposed, 2),
        "infective": round(infective, 2),
        "recovered": round(recovered, 2),
        "deceased": round(deceased, 2)
    }
    print(json.dumps(final_state))

if __name__ == "__main__":
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

    simulate_seird(
        args.test_name,
        args.mortality,
        args.infectivity_period,
        args.dt,
        args.incubation_period,
        args.total_population,
        args.initial_infective,
        args.transmission_rate,
        args.simulation_time
    )
</python_code>
```