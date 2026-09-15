#!/usr/bin/env python3
"""
SEIRD Epidemic Compartmental Model Simulation
Using Discrete Event Simulation with simpy library
"""

import argparse
import json
import sys
import logging
from collections import defaultdict
import simpy


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='SEIRD Epidemic Model Simulation')
    
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
    """SEIRD compartmental model implementation"""
    
    def __init__(self, args):
        self.args = args
        self.env = simpy.Environment()
        
        # Model parameters
        self.mortality = args.mortality / 100.0  # Convert percentage to fraction
        self.infectivity_period = args.infectivity_period
        self.incubation_period = args.incubation_period
        self.transmission_rate = args.transmission_rate
        self.dt = args.dt
        
        # Population compartments
        self.total_population = args.total_population
        self.initial_infective = args.initial_infective
        
        # Initialize compartments
        self.susceptible = self.total_population - self.initial_infective
        self.exposed = 0
        self.infective = self.initial_infective
        self.recovered = 0
        self.deceased = 0
        
        # Track compartment changes
        self.compartment_history = defaultdict(list)
        self.compartment_history['time'].append(0.0)
        self.compartment_history['susceptible'].append(self.susceptible)
        self.compartment_history['exposed'].append(self.exposed)
        self.compartment_history['infective'].append(self.infective)
        self.compartment_history['recovered'].append(self.recovered)
        self.compartment_history['deceased'].append(self.deceased)
        
        # Create processes
        self.env.process(self.run_simulation())
        
    def calculate_transmission(self):
        """Calculate new infections based on current compartment values"""
        if self.susceptible <= 0 or self.infective <= 0:
            return 0.0
            
        # Calculate new exposed individuals
        # Rate: β * S * I / N per day
        transmission_rate = self.transmission_rate * self.susceptible * self.infective / self.total_population
        new_exposed = transmission_rate * self.dt
        
        # Cut the value: new_exposed = min(new_exposed, S_old)
        new_exposed = min(new_exposed, self.susceptible)
        
        return new_exposed
    
    def calculate_incubation(self):
        """Calculate new infectives from exposed individuals"""
        if self.exposed <= 0:
            return 0.0
            
        # Rate: E / incubation_period per day
        incubation_rate = self.exposed / self.incubation_period
        new_infective = incubation_rate * self.dt
        
        # Cut the value: new_infective = min(new_infective, E_old)
        new_infective = min(new_infective, self.exposed)
        
        return new_infective
    
    def calculate_recovery_and_death(self):
        """Calculate new recoveries and deaths from infective individuals"""
        if self.infective <= 0:
            return 0.0, 0.0
            
        # Rate: I / infectivity_period per day
        recovery_rate = self.infective / self.infectivity_period
        
        # Calculate new deceased and recovered
        new_deceased = recovery_rate * self.mortality * self.dt
        new_recovered = recovery_rate * (1 - self.mortality) * self.dt
        
        return new_deceased, new_recovered
    
    def update_compartments(self, new_exposed, new_infective, new_deceased, new_recovered):
        """Update compartment values"""
        # Update susceptible
        self.susceptible -= new_exposed
        
        # Update exposed
        self.exposed += new_exposed - new_infective
        
        # Update infective
        self.infective += new_infective - new_deceased - new_recovered
        
        # Update recovered and deceased
        self.recovered += new_recovered
        self.deceased += new_deceased
        
        # Store history
        self.compartment_history['time'].append(self.env.now)
        self.compartment_history['susceptible'].append(self.susceptible)
        self.compartment_history['exposed'].append(self.exposed)
        self.compartment_history['infective'].append(self.infective)
        self.compartment_history['recovered'].append(self.recovered)
        self.compartment_history['deceased'].append(self.deceased)
        
        # Log current state
        if self.env.now % 1.0 < self.dt:  # Log every day
            logging.debug(f"Time: {self.env.now:.2f} - S: {self.susceptible:.2f}, "
                         f"E: {self.exposed:.2f}, I: {self.infective:.2f}, "
                         f"R: {self.recovered:.2f}, D: {self.deceased:.2f}")
    
    def run_simulation(self):
        """Main simulation loop"""
        while self.env.now < self.args.simulation_time:
            # Calculate transitions
            new_exposed = self.calculate_transmission()
            new_infective = self.calculate_incubation()
            new_deceased, new_recovered = self.calculate_recovery_and_death()
            
            # Update compartments
            self.update_compartments(new_exposed, new_infective, new_deceased, new_recovered)
            
            # Advance time by dt
            yield self.env.timeout(self.dt)
    
    def get_final_state(self):
        """Get the final state of the simulation"""
        return {
            "time": round(self.env.now, 2),
            "susceptible": round(self.susceptible, 2),
            "exposed": round(self.exposed, 2),
            "infective": round(self.infective, 2),
            "recovered": round(self.recovered, 2),
            "deceased": round(self.deceased, 2)
        }


def main():
    """Main function to run the simulation"""
    args = parse_args()
    
    # Set up logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Create and run the model
    model = SEIRDModel(args)
    
    # Run the simulation
    model.env.run()
    
    # Output final state
    final_state = model.get_final_state()
    print(json.dumps(final_state))


if __name__ == "__main__":
    main()