#!/usr/bin/env python3
"""
SEIRD Epidemic Compartmental Model Simulation
============================================

This script simulates infectious disease spread in a closed population using
the SEIRD compartmental model with discrete event simulation.

Compartments:
- S (Susceptible): Individuals who can be infected
- E (Exposed): Individuals who are infected but not yet infectious
- I (Infective): Individuals who are infected and can transmit disease
- R (Recovered): Individuals who have recovered and are immune
- D (Deceased): Individuals who have died from the disease

Model Characteristics:
- Homogeneous mixing: All individuals have equal contact probability
- Closed population: No births, deaths (other than disease), or migration
- Discrete-time: State updates occur at fixed time intervals (dt)
"""

import argparse
import json
import logging
import sys
from collections import defaultdict
import simpy


def parse_args():
    """Parse command line arguments."""
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
    """SEIRD compartmental model implementation."""
    
    def __init__(self, env, params):
        self.env = env
        self.params = params
        
        # Initialize compartments
        self.susceptible = params['total_population'] - params['initial_infective']
        self.exposed = 0
        self.infective = params['initial_infective']
        self.recovered = 0
        self.deceased = 0
        
        # Store compartment history for debugging
        self.history = []
        
        # Create processes for transitions
        self.env.process(self._run_simulation())
        
    def _run_simulation(self):
        """Main simulation loop."""
        # Initial state
        self._log_state()
        
        # Run simulation until end time
        while self.env.now < self.params['simulation_time']:
            # Calculate rates for transitions
            N = self.params['total_population']
            beta = self.params['transmission_rate']
            incubation_period = self.params['incubation_period']
            infectivity_period = self.params['infectivity_period']
            mortality = self.params['mortality']
            
            # Calculate transition rates
            # S -> E: β * S * I / N per day
            if self.susceptible > 0 and self.infective > 0:
                new_exposed = (beta * self.susceptible * self.infective / N) * self.params['dt']
                new_exposed = min(new_exposed, self.susceptible)
            else:
                new_exposed = 0
                
            # E -> I: E / incubation_period per day
            if self.exposed > 0:
                new_infective = (self.exposed / incubation_period) * self.params['dt']
                new_infective = min(new_infective, self.exposed)
            else:
                new_infective = 0
                
            # I -> R: I / infectivity_period * (1 - mortality/100) per day
            if self.infective > 0:
                new_recovered = (self.infective / infectivity_period) * (1 - mortality/100) * self.params['dt']
            else:
                new_recovered = 0
                
            # I -> D: I / infectivity_period * (mortality/100) per day
            if self.infective > 0:
                new_deceased = (self.infective / infectivity_period) * (mortality/100) * self.params['dt']
            else:
                new_deceased = 0
            
            # Update compartments
            self.susceptible = max(0, self.susceptible - new_exposed)
            self.exposed = max(0, self.exposed + new_exposed - new_infective)
            self.infective = max(0, self.infective + new_infective - new_deceased - new_recovered)
            self.recovered = max(0, self.recovered + new_recovered)
            self.deceased = max(0, self.deceased + new_deceased)
            
            # Log state
            self._log_state()
            
            # Wait for next time step
            yield self.env.timeout(self.params['dt'])
    
    def _log_state(self):
        """Log current state of compartments."""
        self.history.append({
            'time': self.env.now,
            'susceptible': self.susceptible,
            'exposed': self.exposed,
            'infective': self.infective,
            'recovered': self.recovered,
            'deceased': self.deceased
        })
        
        # Log to stderr for debugging
        if self.env.now % 1.0 < self.params['dt']:  # Log every day
            logging.debug(f"Time {self.env.now:.2f}: S={self.susceptible:.2f}, E={self.exposed:.2f}, "
                         f"I={self.infective:.2f}, R={self.recovered:.2f}, D={self.deceased:.2f}")


def main():
    """Main function to run the SEIRD simulation."""
    # Parse arguments
    args = parse_args()
    
    # Set up logging
    logging.basicConfig(level=logging.DEBUG, stream=sys.stderr,
                       format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Define simulation parameters
    params = {
        'mortality': args.mortality,
        'infectivity_period': args.infectivity_period,
        'dt': args.dt,
        'incubation_period': args.incubation_period,
        'total_population': args.total_population,
        'initial_infective': args.initial_infective,
        'transmission_rate': args.transmission_rate,
        'simulation_time': args.simulation_time
    }
    
    # Create model
    model = SEIRDModel(env, params)
    
    # Run simulation
    env.run()
    
    # Output final state
    final_state = {
        'time': round(env.now, 2),
        'susceptible': round(model.susceptible, 2),
        'exposed': round(model.exposed, 2),
        'infective': round(model.infective, 2),
        'recovered': round(model.recovered, 2),
        'deceased': round(model.deceased, 2)
    }
    
    print(json.dumps(final_state))


if __name__ == '__main__':
    main()