import argparse
import sys
import json
import logging
from collections import namedtuple

# Configure logging to stderr
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def parse_args():
    parser = argparse.ArgumentParser(description="SEIRD Epidemic Compartmental Model Simulation")
    parser.add_argument('--test_name', type=str, required=True, help='Name of the test case')
    parser.add_argument('--mortality', type=float, default=10.0, help='Mortality rate as percentage (0-100)')
    parser.add_argument('--infectivity_period', type=float, default=14.0, help='Average days a person stays infectious')
    parser.add_argument('--dt', type=float, default=0.1, help='Time step for numerical integration in days')
    parser.add_argument('--incubation_period', type=float, default=5.0, help='Average days from exposure to becoming infectious')
    parser.add_argument('--total_population', type=int, default=1000, help='Total population size')
    parser.add_argument('--initial_infective', type=int, default=10, help='Initial number of infected individuals')
    parser.add_argument('--transmission_rate', type=float, default=2.5, help='Transmission rate (β) per day')
    parser.add_argument('--simulation_time', type=float, default=10.0, help='Total simulation time in days')
    
    return parser.parse_args()

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
    
    # Ensure all compartment counts are non-negative
    susceptible = max(0, susceptible)
    exposed = max(0, exposed)
    infective = max(0, infective)
    recovered = max(0, recovered)
    deceased = max(0, deceased)
    
    # Track time
    current_time = 0.0
    
    # Run simulation
    while current_time < simulation_time:
        # Calculate rates
        # S -> E
        if susceptible > 0 and infective > 0:
            new_exposed = (transmission_rate * susceptible * infective / total_population) * dt
            new_exposed = min(new_exposed, susceptible)
        else:
            new_exposed = 0
        
        # E -> I
        if exposed > 0:
            new_infective = (exposed / incubation_period) * dt
            new_infective = min(new_infective, exposed)
        else:
            new_infective = 0
            
        # I -> R or D
        if infective > 0:
            new_deceased = (infective / infectivity_period) * (mortality / 100.0) * dt
            new_recovered = (infective / infectivity_period) * (1 - mortality / 100.0) * dt
        else:
            new_deceased = 0
            new_recovered = 0
        
        # Update compartments
        susceptible = max(0, susceptible - new_exposed)
        exposed = max(0, exposed + new_exposed - new_infective)
        infective = max(0, infective + new_infective - new_deceased - new_recovered)
        recovered = max(0, recovered + new_recovered)
        deceased = max(0, deceased + new_deceased)
        
        # Update time
        current_time += dt
        
        # Log intermediate steps for debugging
        if current_time % 1.0 < dt:  # Log every day
            logging.info(f"Time: {current_time:.2f}, S: {susceptible:.2f}, E: {exposed:.2f}, I: {infective:.2f}, R: {recovered:.2f}, D: {deceased:.2f}")
    
    # Ensure population conservation
    total = susceptible + exposed + infective + recovered + deceased
    logging.info(f"Final population: {total:.2f} (should be close to {total_population})")
    
    # Output final state
    result = {
        "time": round(current_time, 2),
        "susceptible": round(susceptible, 2),
        "exposed": round(exposed, 2),
        "infective": round(infective, 2),
        "recovered": round(recovered, 2),
        "deceased": round(deceased, 2)
    }
    
    print(json.dumps(result))

def main():
    args = parse_args()
    logging.info(f"Starting simulation with test name: {args.test_name}")
    simulate_seird(args)

if __name__ == "__main__":
    main()