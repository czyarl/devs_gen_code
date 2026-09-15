#!/usr/bin/env python3
"""
SEIRD Epidemic Compartmental Model Simulation
"""

import argparse
import sys
import json
import logging
from collections import defaultdict
import random
import simpy

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)

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
        
    def step(self, env):
        """Perform one simulation step"""
        # Calculate rates
        beta = self.transmission_rate
        N = self.total_population
        
        # Calculate transitions
        # S -> E: Susceptible individuals become exposed
        new_exposed = min((beta * self.susceptible * self.infective / N) * self.dt, self.susceptible)
        
        # E -> I: Exposed individuals become infectious
        new_infective = min((self.exposed / self.incubation_period) * self.dt, self.exposed)
        
        # I -> R: Infective individuals recover
        new_recovered = min((self.infective / self.infectivity_period) * (1 - self.mortality/100) * self.dt, self.infective)
        
        # I -> D: Infective individuals die
        new_deceased = min((self.infective / self.infectivity_period) * (self.mortality/100) * self.dt, self.infective)
        
        # Update compartments
        self.susceptible -= new_exposed
        self.exposed += new_exposed - new_infective
        self.infective += new_infective - new_deceased - new_recovered
        self.recovered += new_recovered
        self.deceased += new_deceased
        
        # Store history for debugging
        self.history.append({
            'time': env.now,
            'susceptible': self.susceptible,
            'exposed': self.exposed,
            'infective': self.infective,
            'recovered': self.recovered,
            'deceased': self.deceased
        })
        
        # Log progress
        if env.now % 1.0 == 0:  # Log every day
            logging.info(f"Time: {env.now:.1f} - S: {self.susceptible:.2f}, E: {self.exposed:.2f}, I: {self.infective:.2f}, R: {self.recovered:.2f}, D: {self.deceased:.2f}")
        
        # Continue simulation
        yield env.timeout(self.dt)
        
    def run_simulation(self):
        """Run the simulation using simpy"""
        env = simpy.Environment()
        
        # Create a process that steps through the simulation
        env.process(self.simulation_process(env))
        
        # Run simulation
        env.run(until=self.simulation_time)
        
        return {
            "time": self.simulation_time,
            "susceptible": round(self.susceptible, 2),
            "exposed": round(self.exposed, 2),
            "infective": round(self.infective, 2),
            "recovered": round(self.recovered, 2),
            "deceased": round(self.deceased, 2)
        }
        
    def simulation_process(self, env):
        """Process that runs the simulation steps"""
        while env.now < self.simulation_time:
            yield from self.step(env)

def main():
    parser = argparse.ArgumentParser(description='SEIRD Epidemic Compartmental Model Simulation')
    parser.add_argument('--test_name', required=True, help='Name of the test case being run')
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
    if not (0 <= args.mortality <= 100):
        logging.error("Mortality rate must be between 0 and 100")
        sys.exit(1)
        
    if args.total_population < 0:
        logging.error("Total population must be non-negative")
        sys.exit(1)
        
    if args.initial_infective < 0:
        logging.error("Initial infective count must be non-negative")
        sys.exit(1)
        
    if args.initial_infective > args.total_population:
        logging.error("Initial infective count cannot exceed total population")
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
    
    # Output final result to stdout
    print(json.dumps(result))

if __name__ == "__main__":
    main()