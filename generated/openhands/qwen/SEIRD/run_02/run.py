#!/usr/bin/env python3
"""
SEIRD Epidemic Compartmental Model Simulation
============================================

This script simulates infectious disease spread in a closed population using
the SEIRD (Susceptible-Exposed-Infective-Recovered-Deceased) compartmental model.

Model compartments:
- S (Susceptible): Individuals who can be infected
- E (Exposed): Individuals who are infected but not yet infectious
- I (Infective): Individuals who are infected and can transmit disease
- R (Recovered): Individuals who have recovered and are immune
- D (Deceased): Individuals who have died from the disease

The simulation uses discrete event simulation with the simpy library.
"""

import argparse
import json
import logging
import sys

import simpy


def parse_arguments():
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
    
    def __init__(self, env, total_population, initial_infective, transmission_rate,
                 infectivity_period, incubation_period, mortality_rate, dt, simulation_time):
        """
        Initialize the SEIRD model.
        
        Args:
            env: SimPy environment
            total_population: Total population size
            initial_infective: Initial number of infected individuals
            transmission_rate: Transmission rate (β) per day
            infectivity_period: Average days a person stays infectious
            incubation_period: Average days from exposure to becoming infectious
            mortality_rate: Mortality rate as percentage (0-100)
            dt: Time step for numerical integration in days
            simulation_time: Total simulation time in days
        """
        self.env = env
        self.total_population = total_population
        self.initial_infective = initial_infective
        self.transmission_rate = transmission_rate
        self.infectivity_period = infectivity_period
        self.incubation_period = incubation_period
        self.mortality_rate = mortality_rate
        self.dt = dt
        self.simulation_time = simulation_time
        
        # Initialize compartments
        self.susceptible = total_population - initial_infective
        self.exposed = 0
        self.infective = initial_infective
        self.recovered = 0
        self.deceased = 0
        
        # Store compartment history for debugging
        self.history = []
        
        # Create processes for transitions
        self.env.process(self._run_simulation())
    
    def _calculate_transitions(self):
        """Calculate transitions between compartments."""
        # Calculate rates
        if self.susceptible > 0 and self.infective > 0:
            # S -> E transition rate: β * S * I / N
            new_exposed_rate = (self.transmission_rate * self.susceptible * self.infective / 
                               self.total_population)
        else:
            new_exposed_rate = 0.0
            
        # E -> I transition rate: E / incubation_period
        new_infective_rate = self.exposed / self.incubation_period if self.exposed > 0 else 0.0
        
        # I -> R and I -> D transition rates
        # I -> R rate: I / infectivity_period * (1 - mortality/100)
        new_recovered_rate = (self.infective / self.infectivity_period * 
                            (1.0 - self.mortality_rate / 100.0)) if self.infective > 0 else 0.0
        
        # I -> D rate: I / infectivity_period * (mortality/100)
        new_deceased_rate = (self.infective / self.infectivity_period * 
                           (self.mortality_rate / 100.0)) if self.infective > 0 else 0.0
        
        # Calculate transitions for this time step
        new_exposed = min(new_exposed_rate * self.dt, self.susceptible)
        new_infective = min(new_infective_rate * self.dt, self.exposed)
        new_recovered = min(new_recovered_rate * self.dt, self.infective)
        new_deceased = min(new_deceased_rate * self.dt, self.infective)
        
        # Update compartments
        self.susceptible -= new_exposed
        self.exposed += new_exposed - new_infective
        self.infective += new_infective - new_recovered - new_deceased
        self.recovered += new_recovered
        self.deceased += new_deceased
        
        # Ensure no negative values
        self.susceptible = max(0, self.susceptible)
        self.exposed = max(0, self.exposed)
        self.infective = max(0, self.infective)
        self.recovered = max(0, self.recovered)
        self.deceased = max(0, self.deceased)
        
        # Store history for debugging
        self.history.append({
            'time': self.env.now,
            'susceptible': self.susceptible,
            'exposed': self.exposed,
            'infective': self.infective,
            'recovered': self.recovered,
            'deceased': self.deceased
        })
    
    def _run_simulation(self):
        """Run the simulation."""
        # Run until simulation time is reached
        while self.env.now < self.simulation_time:
            # Calculate transitions for this time step
            self._calculate_transitions()
            
            # Log current state
            if self.env.now % 1.0 < self.dt:  # Log every day
                logging.debug(f"Time {self.env.now:.2f}: S={self.susceptible:.2f}, "
                              f"E={self.exposed:.2f}, I={self.infective:.2f}, "
                              f"R={self.recovered:.2f}, D={self.deceased:.2f}")
            
            # Wait for next time step
            yield self.env.timeout(self.dt)
    
    def get_final_state(self):
        """Get the final state of the model."""
        return {
            'time': self.env.now,
            'susceptible': round(self.susceptible, 2),
            'exposed': round(self.exposed, 2),
            'infective': round(self.infective, 2),
            'recovered': round(self.recovered, 2),
            'deceased': round(self.deceased, 2)
        }


def main():
    """Main function to run the SEIRD simulation."""
    # Parse arguments
    args = parse_arguments()
    
    # Set up logging
    logging.basicConfig(level=logging.DEBUG if args.test_name == "debug" else logging.WARNING,
                       format='%(asctime)s - %(levelname)s - %(message)s',
                       stream=sys.stderr)
    
    # Log configuration
    logging.debug(f"Configuration: {args}")
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create SEIRD model
    model = SEIRDModel(env, args.total_population, args.initial_infective,
                       args.transmission_rate, args.infectivity_period,
                       args.incubation_period, args.mortality, args.dt, args.simulation_time)
    
    # Run simulation
    logging.debug("Starting simulation...")
    env.run(until=args.simulation_time)
    logging.debug("Simulation completed.")
    
    # Output final state
    final_state = model.get_final_state()
    logging.debug(f"Final state: {final_state}")
    print(json.dumps(final_state))


if __name__ == '__main__':
    main()