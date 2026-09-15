#!/usr/bin/env python3
"""
SEIRD Epidemic Compartmental Model Implementation
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
        
        # Store history for debugging
        self.history = []
        
    def calculate_transmission(self):
        """Calculate new exposed individuals"""
        if self.susceptible <= 0 or self.infective <= 0:
            return 0
            
        # β * S * I / N * dt
        new_exposed = (self.transmission_rate * self.susceptible * self.infective / 
                      self.total_population) * self.dt
        # Cut the value: new_exposed = min(new_exposed, S_old)
        new_exposed = min(new_exposed, self.susceptible)
        return new_exposed
    
    def calculate_exposed_to_infective(self):
        """Calculate new infective individuals from exposed"""
        if self.exposed <= 0:
            return 0
            
        # E / incubation_period * dt
        new_infective = (self.exposed / self.incubation_period) * self.dt
        # Cut the value: new_infective = min(new_infective, E_old)
        new_infective = min(new_infective, self.exposed)
        return new_infective
    
    def calculate_infective_to_recovered_deceased(self):
        """Calculate new recovered and deceased individuals from infective"""
        if self.infective <= 0:
            return 0, 0
            
        # I / infectivity_period * (1 - mortality/100) * dt
        new_recovered = (self.infective / self.infectivity_period) * (1 - self.mortality/100) * self.dt
        # I / infectivity_period * (mortality/100) * dt
        new_deceased = (self.infective / self.infectivity_period) * (self.mortality/100) * self.dt
        
        # Cut the values
        new_recovered = min(new_recovered, self.infective)
        new_deceased = min(new_deceased, self.infective)
        
        return new_recovered, new_deceased
    
    def step(self):
        """Perform one simulation step"""
        # Calculate transitions
        new_exposed = self.calculate_transmission()
        new_infective = self.calculate_exposed_to_infective()
        new_recovered, new_deceased = self.calculate_infective_to_recovered_deceased()
        
        # Update compartments
        old_susceptible = self.susceptible
        old_exposed = self.exposed
        old_infective = self.infective
        
        self.susceptible = max(0, self.susceptible - new_exposed)
        self.exposed = max(0, self.exposed + new_exposed - new_infective)
        self.infective = max(0, self.infective + new_infective - new_recovered - new_deceased)
        self.recovered = max(0, self.recovered + new_recovered)
        self.deceased = max(0, self.deceased + new_deceased)
        
        # Store history for debugging
        self.history.append({
            'susceptible': self.susceptible,
            'exposed': self.exposed,
            'infective': self.infective,
            'recovered': self.recovered,
            'deceased': self.deceased,
            'new_exposed': new_exposed,
            'new_infective': new_infective,
            'new_recovered': new_recovered,
            'new_deceased': new_deceased
        })
        
        # Log progress
        logging.info(f"Step completed - S:{self.susceptible:.2f}, E:{self.exposed:.2f}, "
                    f"I:{self.infective:.2f}, R:{self.recovered:.2f}, D:{self.deceased:.2f}")
    
    def run_simulation(self):
        """Run the full simulation"""
        logging.info("Starting SEIRD simulation")
        logging.info(f"Parameters: mortality={self.mortality}, "
                    f"infectivity_period={self.infectivity_period}, "
                    f"dt={self.dt}, incubation_period={self.incubation_period}, "
                    f"total_population={self.total_population}, "
                    f"initial_infective={self.initial_infective}, "
                    f"transmission_rate={self.transmission_rate}, "
                    f"simulation_time={self.simulation_time}")
        
        # Initial state
        logging.info(f"Initial state - S:{self.susceptible:.2f}, E:{self.exposed:.2f}, "
                    f"I:{self.infective:.2f}, R:{self.recovered:.2f}, D:{self.deceased:.2f}")
        
        # Run simulation
        current_time = 0.0
        while current_time < self.simulation_time:
            self.step()
            current_time += self.dt
            
            # Log every 10 steps for performance
            if int(current_time / self.dt) % 10 == 0:
                logging.info(f"Time: {current_time:.2f}")
        
        # Final state
        logging.info(f"Final state - S:{self.susceptible:.2f}, E:{self.exposed:.2f}, "
                    f"I:{self.infective:.2f}, R:{self.recovered:.2f}, D:{self.deceased:.2f}")
        
        # Verify population conservation
        total = self.susceptible + self.exposed + self.infective + self.recovered + self.deceased
        logging.info(f"Population conservation check: {total:.2f} (expected: {self.total_population})")
        
        return {
            "time": round(self.simulation_time, 2),
            "susceptible": round(self.susceptible, 2),
            "exposed": round(self.exposed, 2),
            "infective": round(self.infective, 2),
            "recovered": round(self.recovered, 2),
            "deceased": round(self.deceased, 2)
        }

def main():
    parser = argparse.ArgumentParser(description='SEIRD Epidemic Compartmental Model')
    parser.add_argument('--test_name', type=str, required=True, help='Name of the test case being run')
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
    
    # Run simulation and output result
    result = model.run_simulation()
    print(json.dumps(result))

if __name__ == "__main__":
    main()