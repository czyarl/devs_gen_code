#!/usr/bin/env python3
"""
SEIRD Epidemic Compartmental Model Simulation
Discrete Event Simulation using simpy
"""

import argparse
import sys
import json
import logging
import simpy


class SEIRDSimulation:
    """SEIRD epidemic model simulation using discrete event simulation."""
    
    def __init__(self, test_name, mortality, infectivity_period, dt, 
                 incubation_period, total_population, initial_infective,
                 transmission_rate, simulation_time):
        self.test_name = test_name
        self.mortality = mortality
        self.infectivity_period = infectivity_period
        self.dt = dt
        self.incubation_period = incubation_period
        self.total_population = total_population
        self.initial_infective = initial_infective
        self.transmission_rate = transmission_rate
        self.simulation_time = simulation_time
        
        # Initialize compartments
        self.susceptible = float(total_population - initial_infective)
        self.exposed = 0.0
        self.infective = float(initial_infective)
        self.recovered = 0.0
        self.deceased = 0.0
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            stream=sys.stderr
        )
        self.logger = logging.getLogger(__name__)
    
    def update_state(self):
        """Update the SEIRD compartments based on transition rates."""
        # Store old values
        S_old = self.susceptible
        E_old = self.exposed
        I_old = self.infective
        R_old = self.recovered
        D_old = self.deceased
        N = self.total_population
        
        # Calculate transitions
        # S -> E: new_exposed = (β * S * I / N) * dt
        new_exposed = (self.transmission_rate * S_old * I_old / N) * self.dt
        new_exposed = min(new_exposed, S_old)
        
        # E -> I: new_infective = (E / incubation_period) * dt
        new_infective = (E_old / self.incubation_period) * self.dt
        new_infective = min(new_infective, E_old)
        
        # I -> D: new_deceased = (I / infectivity_period) * (mortality/100) * dt
        new_deceased = (I_old / self.infectivity_period) * (self.mortality / 100.0) * self.dt
        
        # I -> R: new_recovered = (I / infectivity_period) * (1 - mortality/100) * dt
        new_recovered = (I_old / self.infectivity_period) * (1.0 - self.mortality / 100.0) * self.dt
        
        # Update compartments
        self.susceptible = S_old - new_exposed
        self.exposed = E_old + new_exposed - new_infective
        self.infective = I_old + new_infective - new_deceased - new_recovered
        self.recovered = R_old + new_recovered
        self.deceased = D_old + new_deceased
        
        # Log the transition
        self.logger.debug(
            f"Time: {self.env.now:.2f} - "
            f"S: {self.susceptible:.2f}, E: {self.exposed:.2f}, "
            f"I: {self.infective:.2f}, R: {self.recovered:.2f}, D: {self.deceased:.2f}"
        )
    
    def state_update_process(self, env):
        """Simpy process that updates the state at each time step."""
        while env.now < self.simulation_time:
            self.update_state()
            yield env.timeout(self.dt)
    
    def run(self):
        """Run the simulation."""
        self.logger.info(f"Starting SEIRD simulation: {self.test_name}")
        self.logger.info(f"Parameters: N={self.total_population}, I0={self.initial_infective}, "
                        f"β={self.transmission_rate}, mortality={self.mortality}%, "
                        f"incubation_period={self.incubation_period}, "
                        f"infectivity_period={self.infectivity_period}, "
                        f"dt={self.dt}, simulation_time={self.simulation_time}")
        
        # Create simpy environment
        self.env = simpy.Environment()
        
        # Add state update process
        self.env.process(self.state_update_process(self.env))
        
        # Run simulation
        self.env.run(until=self.simulation_time)
        
        self.logger.info("Simulation completed")
        
        # Output final state
        self.output_final_state()
    
    def output_final_state(self):
        """Output the final state as JSONL to stdout."""
        result = {
            "time": round(self.env.now, 2),
            "susceptible": round(self.susceptible, 2),
            "exposed": round(self.exposed, 2),
            "infective": round(self.infective, 2),
            "recovered": round(self.recovered, 2),
            "deceased": round(self.deceased, 2)
        }
        print(json.dumps(result))
        
        # Verify population conservation
        total = (self.susceptible + self.exposed + self.infective + 
                self.recovered + self.deceased)
        self.logger.info(f"Population check: {total:.2f} / {self.total_population}")


def main():
    """Main entry point for the SEIRD simulation."""
    parser = argparse.ArgumentParser(
        description='SEIRD Epidemic Compartmental Model Simulation'
    )
    
    parser.add_argument(
        '--test_name',
        type=str,
        required=True,
        help='Name of the test case being run'
    )
    parser.add_argument(
        '--mortality',
        type=float,
        default=10.0,
        help='Mortality rate as percentage (0-100)'
    )
    parser.add_argument(
        '--infectivity_period',
        type=float,
        default=14.0,
        help='Average days a person stays infectious'
    )
    parser.add_argument(
        '--dt',
        type=float,
        default=0.1,
        help='Time step for numerical integration in days'
    )
    parser.add_argument(
        '--incubation_period',
        type=float,
        default=5.0,
        help='Average days from exposure to becoming infectious'
    )
    parser.add_argument(
        '--total_population',
        type=int,
        default=1000,
        help='Total population size'
    )
    parser.add_argument(
        '--initial_infective',
        type=int,
        default=10,
        help='Initial number of infected individuals'
    )
    parser.add_argument(
        '--transmission_rate',
        type=float,
        default=2.5,
        help='Transmission rate (β) per day'
    )
    parser.add_argument(
        '--simulation_time',
        type=float,
        default=10.0,
        help='Total simulation time in days'
    )
    
    args = parser.parse_args()
    
    # Create and run simulation
    sim = SEIRDSimulation(
        test_name=args.test_name,
        mortality=args.mortality,
        infectivity_period=args.infectivity_period,
        dt=args.dt,
        incubation_period=args.incubation_period,
        total_population=args.total_population,
        initial_infective=args.initial_infective,
        transmission_rate=args.transmission_rate,
        simulation_time=args.simulation_time
    )
    
    sim.run()


if __name__ == '__main__':
    main()