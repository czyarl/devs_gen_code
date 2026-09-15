#!/usr/bin/env python3
"""
SEIRD Epidemic Compartmental Model Simulation
Using Discrete Event Simulation (DES) with simpy library
"""

import argparse
import json
import logging
import sys
from collections import defaultdict

import simpy


def parse_args():
    """Parse command line arguments."""
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
    """SEIRD compartmental model implementation."""
    
    def __init__(self, env, args):
        self.env = env
        self.args = args
        
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
        
        # Schedule all processes
        self.env.process(self.susceptible_to_exposed())
        self.env.process(self.exposed_to_infective())
        self.env.process(self.infective_to_recovered_or_deceased())
    
    def susceptible_to_exposed(self):
        """Process for susceptible individuals becoming exposed."""
        while True:
            # Calculate rate of transition: β * S * I / N per day
            if self.infective > 0 and self.susceptible > 0:
                rate = self.transmission_rate * self.susceptible * self.infective / self.total_population
                # Calculate number of new exposures in dt time
                new_exposed = rate * self.dt
                
                # Ensure we don't exceed susceptible population
                new_exposed = min(new_exposed, self.susceptible)
                
                if new_exposed > 0:
                    # Update compartments
                    self.susceptible -= new_exposed
                    self.exposed += new_exposed
                    
                    # Log the change
                    self.compartment_history['time'].append(self.env.now)
                    self.compartment_history['susceptible'].append(self.susceptible)
                    self.compartment_history['exposed'].append(self.exposed)
                    self.compartment_history['infective'].append(self.infective)
                    self.compartment_history['recovered'].append(self.recovered)
                    self.compartment_history['deceased'].append(self.deceased)
            
            # Wait for next time step
            yield self.env.timeout(self.dt)
    
    def exposed_to_infective(self):
        """Process for exposed individuals becoming infective."""
        while True:
            # Calculate rate of transition: E / incubation_period per day
            if self.exposed > 0:
                rate = self.exposed / self.incubation_period
                # Calculate number of new infectives in dt time
                new_infective = rate * self.dt
                
                # Ensure we don't exceed exposed population
                new_infective = min(new_infective, self.exposed)
                
                if new_infective > 0:
                    # Update compartments
                    self.exposed -= new_infective
                    self.infective += new_infective
                    
                    # Log the change
                    self.compartment_history['time'].append(self.env.now)
                    self.compartment_history['susceptible'].append(self.susceptible)
                    self.compartment_history['exposed'].append(self.exposed)
                    self.compartment_history['infective'].append(self.infective)
                    self.compartment_history['recovered'].append(self.recovered)
                    self.compartment_history['deceased'].append(self.deceased)
            
            # Wait for next time step
            yield self.env.timeout(self.dt)
    
    def infective_to_recovered_or_deceased(self):
        """Process for infective individuals recovering or dying."""
        while True:
            # Calculate rates of transition
            if self.infective > 0:
                rate = self.infective / self.infectivity_period
                
                # Calculate number of recoveries and deaths in dt time
                new_deceased = rate * self.mortality * self.dt
                new_recovered = rate * (1 - self.mortality) * self.dt
                
                # Ensure we don't exceed infective population
                new_deceased = min(new_deceased, self.infective)
                new_recovered = min(new_recovered, self.infective)
                
                if new_deceased > 0 or new_recovered > 0:
                    # Update compartments
                    self.infective -= (new_deceased + new_recovered)
                    self.recovered += new_recovered
                    self.deceased += new_deceased
                    
                    # Log the change
                    self.compartment_history['time'].append(self.env.now)
                    self.compartment_history['susceptible'].append(self.susceptible)
                    self.compartment_history['exposed'].append(self.exposed)
                    self.compartment_history['infective'].append(self.infective)
                    self.compartment_history['recovered'].append(self.recovered)
                    self.compartment_history['deceased'].append(self.deceased)
            
            # Wait for next time step
            yield self.env.timeout(self.dt)
    
    def final_output(self):
        """Output the final state at the end of simulation."""
        # Wait until simulation time is reached
        yield self.env.timeout(self.args.simulation_time)
        
        # Output final state
        result = {
            "time": round(self.env.now, 2),
            "susceptible": round(self.susceptible, 2),
            "exposed": round(self.exposed, 2),
            "infective": round(self.infective, 2),
            "recovered": round(self.recovered, 2),
            "deceased": round(self.deceased, 2)
        }
        
        print(json.dumps(result))
        sys.stdout.flush()


def main():
    """Main function to run the SEIRD simulation."""
    args = parse_args()
    
    # Set up logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
    
    # Print arguments for debugging
    print(f"Arguments: {args}", file=sys.stderr)
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create and run the model
    model = SEIRDModel(env, args)
    
    # Run simulation
    print(f"Starting simulation for {args.simulation_time} days", file=sys.stderr)
    env.run(until=args.simulation_time)
    print("Simulation completed", file=sys.stderr)
    
    # Print final state directly after simulation
    result = {
        "time": round(args.simulation_time, 2),
        "susceptible": round(model.susceptible, 2),
        "exposed": round(model.exposed, 2),
        "infective": round(model.infective, 2),
        "recovered": round(model.recovered, 2),
        "deceased": round(model.deceased, 2)
    }
    
    print(json.dumps(result))
    sys.stdout.flush()


if __name__ == "__main__":
    main()