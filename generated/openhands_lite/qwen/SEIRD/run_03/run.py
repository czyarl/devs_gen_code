#!/usr/bin/env python3
"""
SEIRD Epidemic Compartmental Model Simulation
============================================

This script simulates infectious disease spread in a closed population using 
the SEIRD compartmental model with Discrete Event Simulation (DES).

Compartments:
- S (Susceptible): Individuals who can be infected
- E (Exposed): Individuals who are infected but not yet infectious  
- I (Infective): Individuals who are infected and can transmit disease
- R (Recovered): Individuals who have recovered and are immune
- D (Deceased): Individuals who have died from the disease

Model Characteristics:
- Homogeneous Mixing: All individuals have equal contact probability
- Closed Population: No births, deaths (other than disease), or migration
- Discrete-Time: State updates occur at fixed time intervals (dt)
"""

import argparse
import json
import logging
import sys
from typing import Dict, List, Tuple

# Import simpy for discrete event simulation
import simpy

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SEIRDModel:
    """SEIRD Epidemic Model using Discrete Event Simulation"""
    
    def __init__(self, 
                 mortality: float = 10.0,
                 infectivity_period: float = 14.0,
                 dt: float = 0.1,
                 incubation_period: float = 5.0,
                 total_population: int = 1000,
                 initial_infective: int = 10,
                 transmission_rate: float = 2.5,
                 simulation_time: float = 10.0):
        """
        Initialize the SEIRD model with given parameters
        
        Args:
            mortality: Mortality rate as percentage (0-100)
            infectivity_period: Average days a person stays infectious
            dt: Time step for numerical integration in days
            incubation_period: Average days from exposure to becoming infectious
            total_population: Total population size
            initial_infective: Initial number of infected individuals
            transmission_rate: Transmission rate (β) per day
            simulation_time: Total simulation time in days
        """
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
        
        # Store history for debugging
        self.history = []
        
        # Calculate rates
        self.beta = transmission_rate
        self.gamma = 1.0 / infectivity_period
        self.mu = mortality / 100.0
        self.sigma = 1.0 / incubation_period
        
        logger.info(f"Initialized SEIRD model with parameters:")
        logger.info(f"  Population: {total_population}")
        logger.info(f"  Initial infective: {initial_infective}")
        logger.info(f"  Transmission rate (β): {transmission_rate}")
        logger.info(f"  Incubation period: {incubation_period} days")
        logger.info(f"  Infectivity period: {infectivity_period} days")
        logger.info(f"  Mortality rate: {mortality}%")
        logger.info(f"  Time step (dt): {dt} days")
        logger.info(f"  Simulation time: {simulation_time} days")
    
    def run_simulation(self) -> Dict[str, float]:
        """
        Run the complete simulation using simpy for discrete event simulation
        
        Returns:
            Final state of the simulation as a dictionary
        """
        logger.info("Starting simulation with DES...")
        
        # Create a simpy environment
        env = simpy.Environment()
        
        # Create processes for each compartment transition
        # We'll schedule events for transitions at appropriate times
        
        # Track the simulation time
        current_time = 0.0
        
        # Run simulation until reaching the target time
        while current_time < self.simulation_time:
            # Calculate new exposures
            if self.susceptible > 0 and self.infective > 0:
                # Calculate new exposures based on transmission rate
                new_exposed = min(
                    (self.beta * self.susceptible * self.infective / self.total_population) * self.dt,
                    self.susceptible
                )
            else:
                new_exposed = 0.0
                
            # Calculate new infectious individuals (from exposed)
            if self.exposed > 0:
                new_infective = min((self.exposed / self.incubation_period) * self.dt, self.exposed)
            else:
                new_infective = 0.0
                
            # Calculate new recoveries and deaths (from infective)
            if self.infective > 0:
                new_deceased = (self.infective / self.infectivity_period) * (self.mortality / 100.0) * self.dt
                new_recovered = (self.infective / self.infectivity_period) * (1 - self.mortality / 100.0) * self.dt
            else:
                new_deceased = 0.0
                new_recovered = 0.0
                
            # Update compartments
            self.susceptible = max(0, self.susceptible - new_exposed)
            self.exposed = max(0, self.exposed + new_exposed - new_infective)
            self.infective = max(0, self.infective + new_infective - new_deceased - new_recovered)
            self.recovered = max(0, self.recovered + new_recovered)
            self.deceased = max(0, self.deceased + new_deceased)
            
            # Store current state
            current_state = {
                'time': current_time,
                'susceptible': self.susceptible,
                'exposed': self.exposed,
                'infective': self.infective,
                'recovered': self.recovered,
                'deceased': self.deceased
            }
            self.history.append(current_state)
            
            # Advance time
            current_time += self.dt
            
            # Ensure we don't overshoot the simulation time
            if current_time > self.simulation_time:
                current_time = self.simulation_time
                
        logger.info(f"Simulation completed at time {current_time}")
        logger.info(f"Final state: S={self.susceptible:.2f}, E={self.exposed:.2f}, I={self.infective:.2f}, R={self.recovered:.2f}, D={self.deceased:.2f}")
        
        return current_state

def parse_args() -> argparse.Namespace:
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='SEIRD Epidemic Compartmental Model Simulation')
    
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

def main():
    """Main function to run the SEIRD simulation"""
    # Parse command line arguments
    args = parse_args()
    
    # Log the test name
    logger.info(f"Running test: {args.test_name}")
    
    # Create and run the model
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
    final_state = model.run_simulation()
    
    # Output final state as JSONL to stdout
    print(json.dumps(final_state))

if __name__ == "__main__":
    main()