#!/usr/bin/env python3
"""
SEIRD Epidemic Compartmental Model Simulation
Uses discrete event simulation to model infectious disease spread.
"""

import argparse
import sys
import json
import logging
import simpy


def setup_logging():
    """Configure logging to stderr."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        stream=sys.stderr
    )
    return logging.getLogger(__name__)


def parse_arguments():
    """Parse command line arguments."""
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
    
    return parser.parse_args()


class SEIRDSimulation:
    """SEIRD Epidemic Model using Discrete Event Simulation."""
    
    def __init__(self, args, logger):
        self.args = args
        self.logger = logger
        
        # Validate arguments
        self._validate_arguments()
        
        # Initialize compartments
        self.susceptible = float(args.total_population - args.initial_infective)
        self.exposed = 0.0
        self.infective = float(args.initial_infective)
        self.recovered = 0.0
        self.deceased = 0.0
        self.total_population = float(args.total_population)
        
        # Simulation parameters
        self.beta = args.transmission_rate
        self.incubation_period = args.incubation_period
        self.infectivity_period = args.infectivity_period
        self.mortality_rate = args.mortality / 100.0
        self.dt = args.dt
        self.simulation_time = args.simulation_time
        
        self.logger.info(f"Initialized SEIRD simulation for test: {args.test_name}")
        self.logger.info(f"Total population: {self.total_population}")
        self.logger.info(f"Initial state - S: {self.susceptible}, E: {self.exposed}, "
                        f"I: {self.infective}, R: {self.recovered}, D: {self.deceased}")
    
    def _validate_arguments(self):
        """Validate input arguments."""
        if self.args.mortality < 0 or self.args.mortality > 100:
            raise ValueError("Mortality rate must be between 0 and 100")
        if self.args.total_population < 0:
            raise ValueError("Total population must be non-negative")
        if self.args.initial_infective < 0:
            raise ValueError("Initial infective must be non-negative")
        if self.args.initial_infective > self.args.total_population:
            raise ValueError("Initial infective cannot exceed total population")
        if self.args.dt <= 0:
            raise ValueError("Time step (dt) must be positive")
        if self.args.incubation_period <= 0:
            raise ValueError("Incubation period must be positive")
        if self.args.infectivity_period <= 0:
            raise ValueError("Infectivity period must be positive")
        if self.args.simulation_time < 0:
            raise ValueError("Simulation time must be non-negative")
    
    def update_compartments(self):
        """Update compartment states based on SEIRD model equations."""
        # Store old values
        S_old = self.susceptible
        E_old = self.exposed
        I_old = self.infective
        R_old = self.recovered
        D_old = self.deceased
        N = self.total_population
        
        # Calculate transitions
        # S -> E: Susceptible become exposed
        new_exposed = (self.beta * S_old * I_old / N) * self.dt
        new_exposed = min(new_exposed, S_old)
        
        # E -> I: Exposed become infectious
        new_infective = (E_old / self.incubation_period) * self.dt
        new_infective = min(new_infective, E_old)
        
        # I -> D: Infective die
        new_deceased = (I_old / self.infectivity_period) * self.mortality_rate * self.dt
        
        # I -> R: Infective recover
        new_recovered = (I_old / self.infectivity_period) * (1 - self.mortality_rate) * self.dt
        
        # Update compartments
        self.susceptible = S_old - new_exposed
        self.exposed = E_old + new_exposed - new_infective
        self.infective = I_old + new_infective - new_deceased - new_recovered
        self.recovered = R_old + new_recovered
        self.deceased = D_old + new_deceased
        
        # Ensure non-negative values (floating point precision)
        self.susceptible = max(0.0, self.susceptible)
        self.exposed = max(0.0, self.exposed)
        self.infective = max(0.0, self.infective)
        self.recovered = max(0.0, self.recovered)
        self.deceased = max(0.0, self.deceased)
    
    def run(self):
        """Run the simulation using simpy."""
        self.logger.info(f"Starting simulation for {self.simulation_time} days with dt={self.dt}")
        
        # Create simpy environment
        env = simpy.Environment()
        
        # Simulation process
        def simulation_process(env):
            current_time = 0.0
            while current_time < self.simulation_time:
                # Update compartments
                self.update_compartments()
                
                # Advance time
                current_time += self.dt
                
                # Yield to simpy scheduler
                yield env.timeout(self.dt)
        
        # Add process to environment
        env.process(simulation_process(env))
        
        # Run simulation
        env.run(until=self.simulation_time)
        
        self.logger.info("Simulation completed")
        self.logger.info(f"Final state - S: {self.susceptible:.2f}, E: {self.exposed:.2f}, "
                        f"I: {self.infective:.2f}, R: {self.recovered:.2f}, D: {self.deceased:.2f}")
        
        # Verify population conservation
        total = self.susceptible + self.exposed + self.infective + self.recovered + self.deceased
        self.logger.info(f"Population check: {total:.2f} (expected: {self.total_population})")
    
    def get_final_state(self):
        """Return the final state as a dictionary."""
        return {
            "time": round(self.simulation_time, 2),
            "susceptible": round(self.susceptible, 2),
            "exposed": round(self.exposed, 2),
            "infective": round(self.infective, 2),
            "recovered": round(self.recovered, 2),
            "deceased": round(self.deceased, 2)
        }


def main():
    """Main entry point."""
    # Setup logging
    logger = setup_logging()
    
    # Parse arguments
    args = parse_arguments()
    
    try:
        # Create and run simulation
        simulation = SEIRDSimulation(args, logger)
        simulation.run()
        
        # Output final state as JSONL
        final_state = simulation.get_final_state()
        print(json.dumps(final_state))
        
    except Exception as e:
        logger.error(f"Simulation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()