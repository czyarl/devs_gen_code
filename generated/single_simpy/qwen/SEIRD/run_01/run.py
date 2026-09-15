import argparse
import json
import sys
import logging
from collections import namedtuple

# Configure logging to stderr
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Define a named tuple for compartment counts
Compartment = namedtuple('Compartment', ['susceptible', 'exposed', 'infective', 'recovered', 'deceased'])

def simulate_seird(args):
    # Extract parameters
    mortality = args.mortality
    infectivity_period = args.infectivity_period
    dt = args.dt
    incubation_period = args.incubation_period
    total_population = args.total_population
    initial_infective = args.initial_infective
    transmission_rate = args.transmission_rate
    simulation_time = args.simulation_time
    
    # Initialize compartments
    susceptible = total_population - initial_infective
    exposed = 0
    infective = initial_infective
    recovered = 0
    deceased = 0
    
    # Simulation loop
    time = 0.0
    
    while time < simulation_time:
        # Calculate rates
        # S -> E
        new_exposed = (transmission_rate * susceptible * infective / total_population) * dt
        new_exposed = min(new_exposed, susceptible)
        
        # E -> I
        new_infective = (exposed / incubation_period) * dt
        new_infective = min(new_infective, exposed)
        
        # I -> R and I -> D
        new_deceased = (infective / infectivity_period) * (mortality / 100.0) * dt
        new_recovered = (infective / infectivity_period) * (1 - mortality / 100.0) * dt
        
        # Update compartments
        susceptible -= new_exposed
        exposed += new_exposed - new_infective
        infective += new_infective - new_deceased - new_recovered
        recovered += new_recovered
        deceased += new_deceased
        
        # Advance time
        time += dt
        
        # Ensure population conservation
        total = susceptible + exposed + infective + recovered + deceased
        if abs(total - total_population) > 1e-6:
            logging.warning(f"Population conservation violated at time {time:.2f}: {total} != {total_population}")
    
    # Output final state
    result = {
        "time": round(time, 2),
        "susceptible": round(susceptible, 2),
        "exposed": round(exposed, 2),
        "infective": round(infective, 2),
        "recovered": round(recovered, 2),
        "deceased": round(deceased, 2)
    }
    
    print(json.dumps(result))

def main():
    parser = argparse.ArgumentParser(description="SEIRD Epidemic Compartmental Model Simulation")
    
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
    
    # Validate arguments
    if args.total_population <= 0:
        logging.error("Total population must be positive")
        sys.exit(1)
    if args.initial_infective < 0 or args.initial_infective > args.total_population:
        logging.error("Initial infective must be between 0 and total population")
        sys.exit(1)
    if args.mortality < 0 or args.mortality > 100:
        logging.error("Mortality must be between 0 and 100")
        sys.exit(1)
    if args.infectivity_period <= 0:
        logging.error("Infectivity period must be positive")
        sys.exit(1)
    if args.incubation_period <= 0:
        logging.error("Incubation period must be positive")
        sys.exit(1)
    if args.dt <= 0:
        logging.error("Time step must be positive")
        sys.exit(1)
    if args.simulation_time <= 0:
        logging.error("Simulation time must be positive")
        sys.exit(1)
    
    # Run simulation
    simulate_seird(args)

if __name__ == "__main__":
    main()