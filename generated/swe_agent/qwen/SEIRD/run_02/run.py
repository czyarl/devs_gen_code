#!/usr/bin/env python3
"""
SEIRD Epidemic Compartmental Model Implementation using SimPy
"""

import argparse
import sys
import json
import logging
import simpy

# Set up logging to stderr
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)
logger = logging.getLogger(__name__)

def parse_arguments():
    """Parse command line arguments"""
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
        
        # Start the simulation process
        self.env.process(self.simulation_process())
        
    def simulation_process(self):
        """Main simulation process"""
        logger.info("Starting simulation...")
        
        # Run simulation until time limit
        while self.time < self.simulation_time - self.dt/2:  # Use a small tolerance
            yield self.env.timeout(self.dt)
            self.step()
            
        # Ensure we reach exactly the simulation time
        if self.time < self.simulation_time:
            remaining_time = self.simulation_time - self.time
            yield self.env.timeout(remaining_time)
            self.step()
            
        logger.info("Simulation completed")
        
    def step(self):
        """Perform one simulation step"""
        # Calculate rates
        if self.total_population > 0:
            transmission_rate = (self.transmission_rate * self.susceptible * self.infective) / self.total_population
        else:
            transmission_rate = 0
            
        # Calculate new exposed individuals
        new_exposed = transmission_rate * self.dt
        new_exposed = min(new_exposed, self.susceptible)
        
        # Calculate new infective individuals (from exposed)
        if self.incubation_period > 0:
            new_infective = (self.exposed / self.incubation_period) * self.dt
        else:
            new_infective = 0
        new_infective = min(new_infective, self.exposed)
        
        # Calculate new recovered and deceased individuals (from infective)
        if self.infectivity_period > 0:
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
        
        # Update time
        self.time += self.dt
        
        # Log progress
        if self.time % 1.0 < self.dt:  # Log every 1 day
            logger.info(f"Time: {self.time:.2f}, S: {self.susceptible:.2f}, E: {self.exposed:.2f}, "
                       f"I: {self.infective:.2f}, R: {self.recovered:.2f}, D: {self.deceased:.2f}")
        
    def get_final_state(self):
        """Get the final state of the model"""
        return {
            "time": round(self.simulation_time, 2),  # Use exact simulation time
            "susceptible": round(self.susceptible, 2),
            "exposed": round(self.exposed, 2),
            "infective": round(self.infective, 2),
            "recovered": round(self.recovered, 2),
            "deceased": round(self.deceased, 2)
        }

def main():
    """Main function"""
    args = parse_arguments()
    
    # Create and run the model
    model = SEIRDModel(args)
    model.env.run()
    
    # Output final state
    final_state = model.get_final_state()
    print(json.dumps(final_state))

if __name__ == "__main__":
    main()