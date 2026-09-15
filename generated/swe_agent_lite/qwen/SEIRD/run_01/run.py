#!/usr/bin/env python3
"""
SEIRD Epidemic Compartmental Model Simulation
Using Discrete Event Simulation with simpy library
"""

import argparse
import sys
import json
import logging
from collections import defaultdict
import random
import simpy
import xdevs

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SEIRDModel:
    """SEIRD compartmental model implementation"""
    
    def __init__(self, mortality=10.0, infectivity_period=14.0, dt=0.1, 
                 incubation_period=5.0, total_population=1000, initial_infective=10, 
                 transmission_rate=2.5, simulation_time=10.0):
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
        
    def calculate_transitions(self, time):
        """Calculate transitions between compartments at given time"""
        # Calculate new exposed individuals
        if self.susceptible > 0 and self.infective > 0:
            new_exposed = (self.transmission_rate * self.susceptible * self.infective / 
                          self.total_population) * self.dt
            new_exposed = min(new_exposed, self.susceptible)
        else:
            new_exposed = 0
            
        # Calculate new infectious individuals (from exposed)
        if self.exposed > 0:
            new_infective = (self.exposed / self.incubation_period) * self.dt
            new_infective = min(new_infective, self.exposed)
        else:
            new_infective = 0
            
        # Calculate new recovered and deceased individuals (from infective)
        if self.infective > 0:
            new_deceased = (self.infective / self.infectivity_period) * (self.mortality / 100.0) * self.dt
            new_recovered = (self.infective / self.infectivity_period) * (1 - self.mortality / 100.0) * self.dt
        else:
            new_deceased = 0
            new_recovered = 0
            
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
        
        logger.debug(f"Time {time}: S={self.susceptible:.2f}, E={self.exposed:.2f}, "
                     f"I={self.infective:.2f}, R={self.recovered:.2f}, D={self.deceased:.2f}")
        
    def run_simulation(self):
        """Run the simulation for the specified time"""
        logger.info("Starting SEIRD simulation")
        logger.info(f"Parameters: mortality={self.mortality}, infectivity_period={self.infectivity_period}, "
                    f"dt={self.dt}, incubation_period={self.incubation_period}, "
                    f"total_population={self.total_population}, initial_infective={self.initial_infective}, "
                    f"transmission_rate={self.transmission_rate}, simulation_time={self.simulation_time}")
        
        # Initialize at time 0.0
        self.calculate_transitions(0.0)
        
        # Run simulation in discrete time steps
        current_time = 0.0
        while current_time < self.simulation_time:
            current_time += self.dt
            self.calculate_transitions(current_time)
            
        # Final state
        self.calculate_transitions(self.simulation_time)
        
        logger.info("Simulation completed")
        return {
            "time": round(self.simulation_time, 2),
            "susceptible": round(self.susceptible, 2),
            "exposed": round(self.exposed, 2),
            "infective": round(self.infective, 2),
            "recovered": round(self.recovered, 2),
            "deceased": round(self.deceased, 2)
        }

def main():
    """Main function to parse arguments and run simulation"""
    parser = argparse.ArgumentParser(description='SEIRD Epidemic Compartmental Model')
    parser.add_argument('--test_name', type=str, required=True, 
                       help='Name of the test case being run')
    parser.add_argument('--mortality', type=float, default=10.0,
                       help='Mortality rate as percentage (0-100). Default: 10.0')
    parser.add_argument('--infectivity_period', type=float, default=14.0,
                       help='Average days a person stays infectious. Default: 14.0')
    parser.add_argument('--dt', type=float, default=0.1,
                       help='Time step for numerical integration in days. Default: 0.1')
    parser.add_argument('--incubation_period', type=float, default=5.0,
                       help='Average days from exposure to becoming infectious. Default: 5.0')
    parser.add_argument('--total_population', type=int, default=1000,
                       help='Total population size. Default: 1000')
    parser.add_argument('--initial_infective', type=int, default=10,
                       help='Initial number of infected individuals. Default: 10')
    parser.add_argument('--transmission_rate', type=float, default=2.5,
                       help='Transmission rate (β) per day. Default: 2.5')
    parser.add_argument('--simulation_time', type=float, default=10.0,
                       help='Total simulation time in days. Default: 10.0')
    
    args = parser.parse_args()
    
    # Validate arguments
    if not (0 <= args.mortality <= 100):
        logger.error("Mortality rate must be between 0 and 100")
        sys.exit(1)
        
    if args.total_population < 0:
        logger.error("Total population must be non-negative")
        sys.exit(1)
        
    if args.initial_infective < 0:
        logger.error("Initial infective count must be non-negative")
        sys.exit(1)
        
    if args.initial_infective > args.total_population:
        logger.error("Initial infective count cannot exceed total population")
        sys.exit(1)
        
    # Create and run model
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
    
    # Run simulation
    result = model.run_simulation()
    
    # Output final state to stdout (JSONL)
    print(json.dumps(result))
    
    # Log additional information to stderr
    logger.info(f"Test case: {args.test_name}")
    logger.info(f"Final state: {result}")

if __name__ == "__main__":
    main()