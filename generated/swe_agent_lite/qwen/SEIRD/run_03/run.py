#!/usr/bin/env python3
"""
SEIRD Epidemic Compartmental Model Simulation
Using Discrete Event Simulation with simpy
"""

import argparse
import sys
import json
import logging
from collections import defaultdict
import random
import simpy

# Set up logging to stderr
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SEIRDModel:
    def __init__(self, 
                 mortality=10.0,
                 infectivity_period=14.0,
                 dt=0.1,
                 incubation_period=5.0,
                 total_population=1000,
                 initial_infective=10,
                 transmission_rate=2.5,
                 simulation_time=10.0):
        self.mortality = mortality
        self.infectivity_period = infectivity_period
        self.dt = dt
        self.incubation_period = incubation_period
        self.total_population = total_population
        self.initial_infective = initial_infective
        self.transmission_rate = transmission_rate
        self.simulation_time = simulation_time
        
        # Initialize compartments
        self.susceptible = total_population - initial_infective
        self.exposed = 0
        self.infective = initial_infective
        self.recovered = 0
        self.deceased = 0
        
        # Track history for debugging
        self.history = []
        
    def get_compartments(self):
        """Return current compartment values"""
        return {
            "time": 0.0,
            "susceptible": round(self.susceptible, 2),
            "exposed": round(self.exposed, 2),
            "infective": round(self.infective, 2),
            "recovered": round(self.recovered, 2),
            "deceased": round(self.deceased, 2)
        }
    
    def update_compartments(self, time):
        """Update compartments based on SEIRD model equations"""
        # Calculate rates
        if self.susceptible > 0 and self.infective > 0:
            new_exposed = (self.transmission_rate * self.susceptible * self.infective / self.total_population) * self.dt
            new_exposed = min(new_exposed, self.susceptible)
        else:
            new_exposed = 0
            
        new_infective = (self.exposed / self.incubation_period) * self.dt
        new_infective = min(new_infective, self.exposed)
        
        new_deceased = (self.infective / self.infectivity_period) * (self.mortality / 100.0) * self.dt
        new_recovered = (self.infective / self.infectivity_period) * (1 - self.mortality / 100.0) * self.dt
        
        # Update compartments
        self.susceptible = max(0, self.susceptible - new_exposed)
        self.exposed = max(0, self.exposed + new_exposed - new_infective)
        self.infective = max(0, self.infective + new_infective - new_deceased - new_recovered)
        self.recovered = max(0, self.recovered + new_recovered)
        self.deceased = max(0, self.deceased + new_deceased)
        
        # Store history for debugging
        self.history.append({
            "time": time,
            "susceptible": round(self.susceptible, 2),
            "exposed": round(self.exposed, 2),
            "infective": round(self.infective, 2),
            "recovered": round(self.recovered, 2),
            "deceased": round(self.deceased, 2)
        })
        
        # Log progress
        if time % 1.0 == 0:  # Log every day
            logging.info(f"Time {time:.1f}: S={self.susceptible:.2f}, E={self.exposed:.2f}, I={self.infective:.2f}, R={self.recovered:.2f}, D={self.deceased:.2f}")

def run_simulation(args):
    """Run the SEIRD simulation"""
    # Create model
    model = SEIRDModel(
        mortality=args.mortality,
        infectivity_period=args.infectivity_period,
        dt=args.dt,
        incubation_period=args.incubation_period,
        total_population=args.total_population,
        initial_infective=args.initial_infective,
        transmission_rate=args.transmission_rate,
        simulation_time=args.simulation_time
    )
    
    # Simulate
    current_time = 0.0
    while current_time < args.simulation_time:
        model.update_compartments(current_time)
        current_time += args.dt
    
    # Output final state
    final_state = model.get_compartments()
    final_state["time"] = args.simulation_time
    print(json.dumps(final_state))

def main():
    """Main function to parse arguments and run simulation"""
    parser = argparse.ArgumentParser(description='SEIRD Epidemic Compartmental Model Simulation')
    
    parser.add_argument('--test_name', required=True, type=str, help='Name of the test case being run')
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
    if args.mortality < 0 or args.mortality > 100:
        logging.error("Mortality rate must be between 0 and 100")
        sys.exit(1)
        
    if args.infectivity_period <= 0:
        logging.error("Infectivity period must be positive")
        sys.exit(1)
        
    if args.dt <= 0:
        logging.error("Time step must be positive")
        sys.exit(1)
        
    if args.incubation_period <= 0:
        logging.error("Incubation period must be positive")
        sys.exit(1)
        
    if args.total_population < 0:
        logging.error("Total population must be non-negative")
        sys.exit(1)
        
    if args.initial_infective < 0:
        logging.error("Initial infective count must be non-negative")
        sys.exit(1)
        
    if args.transmission_rate < 0:
        logging.error("Transmission rate must be non-negative")
        sys.exit(1)
        
    if args.simulation_time <= 0:
        logging.error("Simulation time must be positive")
        sys.exit(1)
    
    # Run simulation
    run_simulation(args)

if __name__ == "__main__":
    main()