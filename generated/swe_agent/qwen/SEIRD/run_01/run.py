#!/usr/bin/env python3
"""
SEIRD Epidemic Compartmental Model Implementation using SimPy
"""

import argparse
import sys
import json
import logging
import simpy

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)
logger = logging.getLogger(__name__)

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='SEIRD Epidemic Compartmental Model')
    
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

class SEIRDModel:
    """SEIRD compartmental model implementation using SimPy"""
    
    def __init__(self, args):
        self.args = args
        self.env = simpy.Environment()
        self.time = 0.0
        self.susceptible = args.total_population - args.initial_infective
        self.exposed = 0
        self.infective = args.initial_infective
        self.recovered = 0
        self.deceased = 0
        self.total_population = args.total_population
        
        # Model parameters
        self.mortality = args.mortality
        self.infectivity_period = args.infectivity_period
        self.dt = args.dt
        self.incubation_period = args.incubation_period
        self.transmission_rate = args.transmission_rate
        self.simulation_time = args.simulation_time
        
        logger.info(f"Initialized SEIRD model with parameters: {vars(args)}")
        
        # Start simulation processes
        self.env.process(self.run_simulation())
        
    def calculate_transitions(self):
        """Calculate compartment transitions based on current state"""
        # Calculate new exposed individuals
        if self.susceptible > 0 and self.infective > 0:
            new_exposed = (self.transmission_rate * self.susceptible * self.infective / self.total_population) * self.dt
            new_exposed = min(new_exposed, self.susceptible)
        else:
            new_exposed = 0.0
            
        # Calculate new infective individuals (from exposed)
        if self.exposed > 0:
            new_infective = (self.exposed / self.incubation_period) * self.dt
            new_infective = min(new_infective, self.exposed)
        else:
            new_infective = 0.0
            
        # Calculate new recovered and deceased individuals (from infective)
        if self.infective > 0:
            new_deceased = (self.infective / self.infectivity_period) * (self.mortality / 100.0) * self.dt
            new_recovered = (self.infective / self.infectivity_period) * (1 - self.mortality / 100.0) * self.dt
        else:
            new_deceased = 0.0
            new_recovered = 0.0
            
        return new_exposed, new_infective, new_deceased, new_recovered
    
    def update_compartments(self, new_exposed, new_infective, new_deceased, new_recovered):
        """Update compartment counts"""
        self.susceptible = max(0, self.susceptible - new_exposed)
        self.exposed = max(0, self.exposed + new_exposed - new_infective)
        self.infective = max(0, self.infective + new_infective - new_deceased - new_recovered)
        self.recovered = max(0, self.recovered + new_recovered)
        self.deceased = max(0, self.deceased + new_deceased)
        
        # Ensure population conservation
        current_total = self.susceptible + self.exposed + self.infective + self.recovered + self.deceased
        if abs(current_total - self.total_population) > 1e-6:
            logger.warning(f"Population conservation violated: {current_total} vs {self.total_population}")
            
    def run_simulation(self):
        """Run the simulation using SimPy"""
        logger.info(f"Starting simulation for {self.simulation_time} days with dt={self.dt}")
        
        # Run simulation until time limit
        while self.time < self.simulation_time - self.dt/2:  # Use a small tolerance
            # Calculate transitions
            new_exposed, new_infective, new_deceased, new_recovered = self.calculate_transitions()
            
            # Update compartments
            self.update_compartments(new_exposed, new_infective, new_deceased, new_recovered)
            
            # Update time
            self.time += self.dt
            
            # Log progress
            if self.time % 1.0 < self.dt:  # Log every day
                logger.info(f"Time: {self.time:.2f} - S: {self.susceptible:.2f}, E: {self.exposed:.2f}, I: {self.infective:.2f}, R: {self.recovered:.2f}, D: {self.deceased:.2f}")
            
            # Wait for next time step
            yield self.env.timeout(self.dt)
        
        # Final update to reach exact simulation time
        new_exposed, new_infective, new_deceased, new_recovered = self.calculate_transitions()
        self.update_compartments(new_exposed, new_infective, new_deceased, new_recovered)
        self.time = self.simulation_time  # Ensure exact time
        
        # Final output
        result = {
            "time": round(self.time, 2),
            "susceptible": round(self.susceptible, 2),
            "exposed": round(self.exposed, 2),
            "infective": round(self.infective, 2),
            "recovered": round(self.recovered, 2),
            "deceased": round(self.deceased, 2)
        }
        
        print(json.dumps(result))
        logger.info(f"Simulation completed. Final state: {result}")

def main():
    """Main function"""
    args = parse_arguments()
    logger.info(f"Starting SEIRD simulation for test: {args.test_name}")
    
    # Create and run model
    model = SEIRDModel(args)
    model.env.run()
    logger.info("Simulation finished")

if __name__ == "__main__":
    main()