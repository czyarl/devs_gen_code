#!/usr/bin/env python3
"""
SEIRD Epidemic Compartmental Model Simulation

This script simulates infectious disease spread in a closed population using
the SEIRD compartmental model with discrete event simulation.
"""

import argparse
import sys
import json
import logging
import simpy


class SEIRDSimulation:
    """SEIRD Epidemic Model Simulation using Discrete Event Simulation"""
    
    def __init__(self, env, config):
        """
        Initialize the SEIRD simulation.
        
        Args:
            env: SimPy environment
            config: Dictionary containing simulation parameters
        """
        self.env = env
        self.config = config
        
        # Initialize compartments
        self.susceptible = float(config['total_population'] - config['initial_infective'])
        self.exposed = 0.0
        self.infective = float(config['initial_infective'])
        self.recovered = 0.0
        self.deceased = 0.0
        
        # Simulation parameters
        self.beta = config['transmission_rate']
        self.mortality = config['mortality']
        self.infectivity_period = config['infectivity_period']
        self.incubation_period = config['incubation_period']
        self.dt = config['dt']
        self.total_population = float(config['total_population'])
        
        # Log initial state
        logging.info(f"Initial state at time 0.0: S={self.susceptible:.2f}, "
                    f"E={self.exposed:.2f}, I={self.infective:.2f}, "
                    f"R={self.recovered:.2f}, D={self.deceased:.2f}")
    
    def update_compartments(self):
        """
        Update compartment states based on transition rates.
        
        This implements the discrete-time SEIRD model with the following transitions:
        - S → E: Susceptible individuals become exposed
        - E → I: Exposed individuals become infectious
        - I → R: Infective individuals recover
        - I → D: Infective individuals die
        """
        # Store old values
        S_old = self.susceptible
        E_old = self.exposed
        I_old = self.infective
        R_old = self.recovered
        D_old = self.deceased
        
        # Calculate transitions
        # S → E: new_exposed = (β * S_old * I_old / N) * dt
        new_exposed = (self.beta * S_old * I_old / self.total_population) * self.dt
        # Cut the value to not exceed available susceptible
        new_exposed = min(new_exposed, S_old)
        
        # E → I: new_infective = (E_old / incubation_period) * dt
        new_infective = (E_old / self.incubation_period) * self.dt
        # Cut the value to not exceed available exposed
        new_infective = min(new_infective, E_old)
        
        # I → D: new_deceased = (I_old / infectivity_period) * (mortality/100) * dt
        new_deceased = (I_old / self.infectivity_period) * (self.mortality / 100.0) * self.dt
        
        # I → R: new_recovered = (I_old / infectivity_period) * (1 - mortality/100) * dt
        new_recovered = (I_old / self.infectivity_period) * (1.0 - self.mortality / 100.0) * self.dt
        
        # Update compartments
        self.susceptible = S_old - new_exposed
        self.exposed = E_old + new_exposed - new_infective
        self.infective = I_old + new_infective - new_deceased - new_recovered
        self.recovered = R_old + new_recovered
        self.deceased = D_old + new_deceased
        
        # Log the update
        logging.debug(f"Time {self.env.time:.2f}: transitions - "
                     f"S→E: {new_exposed:.4f}, E→I: {new_infective:.4f}, "
                     f"I→R: {new_recovered:.4f}, I→D: {new_deceased:.4f}")
    
    def run(self):
        """Run the simulation process."""
        while self.env.time < self.config['simulation_time']:
            # Update compartments
            self.update_compartments()
            
            # Log current state
            logging.debug(f"Time {self.env.time:.2f}: S={self.susceptible:.2f}, "
                         f"E={self.exposed:.2f}, I={self.infective:.2f}, "
                         f"R={self.recovered:.2f}, D={self.deceased:.2f}")
            
            # Advance time by dt
            yield self.env.timeout(self.dt)
    
    def get_final_state(self):
        """
        Get the final state of the simulation.
        
        Returns:
            Dictionary with final compartment values
        """
        total = self.susceptible + self.exposed + self.infective + self.recovered + self.deceased
        logging.info(f"Final state at time {self.env.time:.2f}: S={self.susceptible:.2f}, "
                    f"E={self.exposed:.2f}, I={self.infective:.2f}, "
                    f"R={self.recovered:.2f}, D={self.deceased:.2f}")
        logging.info(f"Total population: {total:.2f} (expected: {self.total_population:.2f})")
        
        return {
            "time": round(self.env.time, 2),
            "susceptible": round(self.susceptible, 2),
            "exposed": round(self.exposed, 2),
            "infective": round(self.infective, 2),
            "recovered": round(self.recovered, 2),
            "deceased": round(self.deceased, 2)
        }


def parse_arguments():
    """
    Parse command line arguments.
    
    Returns:
        Parsed arguments namespace
    """
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
        help='Mortality rate as percentage (0-100). Default: 10.0'
    )
    
    parser.add_argument(
        '--infectivity_period',
        type=float,
        default=14.0,
        help='Average days a person stays infectious. Default: 14.0'
    )
    
    parser.add_argument(
        '--dt',
        type=float,
        default=0.1,
        help='Time step for numerical integration in days. Default: 0.1'
    )
    
    parser.add_argument(
        '--incubation_period',
        type=float,
        default=5.0,
        help='Average days from exposure to becoming infectious. Default: 5.0'
    )
    
    parser.add_argument(
        '--total_population',
        type=int,
        default=1000,
        help='Total population size. An integer >= 0. Default: 1000'
    )
    
    parser.add_argument(
        '--initial_infective',
        type=int,
        default=10,
        help='Initial number of infected individuals. Default: 10'
    )
    
    parser.add_argument(
        '--transmission_rate',
        type=float,
        default=2.5,
        help='Transmission rate (β) per day. Default: 2.5'
    )
    
    parser.add_argument(
        '--simulation_time',
        type=float,
        default=10.0,
        help='Total simulation time in days. Default: 10.0'
    )
    
    return parser.parse_args()


def validate_arguments(args):
    """
    Validate command line arguments.
    
    Args:
        args: Parsed arguments namespace
        
    Raises:
        ValueError: If any argument is invalid
    """
    if args.mortality < 0 or args.mortality > 100:
        raise ValueError(f"Mortality rate must be between 0 and 100, got {args.mortality}")
    
    if args.infectivity_period <= 0:
        raise ValueError(f"Infectivity period must be positive, got {args.infectivity_period}")
    
    if args.dt <= 0:
        raise ValueError(f"Time step (dt) must be positive, got {args.dt}")
    
    if args.incubation_period <= 0:
        raise ValueError(f"Incubation period must be positive, got {args.incubation_period}")
    
    if args.total_population < 0:
        raise ValueError(f"Total population must be non-negative, got {args.total_population}")
    
    if args.initial_infective < 0:
        raise ValueError(f"Initial infective must be non-negative, got {args.initial_infective}")
    
    if args.initial_infective > args.total_population:
        raise ValueError(f"Initial infective ({args.initial_infective}) cannot exceed "
                        f"total population ({args.total_population})")
    
    if args.transmission_rate < 0:
        raise ValueError(f"Transmission rate must be non-negative, got {args.transmission_rate}")
    
    if args.simulation_time < 0:
        raise ValueError(f"Simulation time must be non-negative, got {args.simulation_time}")


def setup_logging(test_name):
    """
    Setup logging configuration.
    
    Args:
        test_name: Name of the test case
    """
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        stream=sys.stderr
    )
    logging.info(f"Starting SEIRD simulation for test: {test_name}")


def main():
    """Main entry point for the SEIRD simulation."""
    # Parse command line arguments
    args = parse_arguments()
    
    # Validate arguments
    try:
        validate_arguments(args)
    except ValueError as e:
        logging.error(f"Invalid arguments: {e}")
        sys.exit(1)
    
    # Setup logging
    setup_logging(args.test_name)
    
    # Log configuration
    logging.info(f"Configuration: test_name={args.test_name}, "
                f"mortality={args.mortality}%, "
                f"infectivity_period={args.infectivity_period} days, "
                f"dt={args.dt} days, "
                f"incubation_period={args.incubation_period} days, "
                f"total_population={args.total_population}, "
                f"initial_infective={args.initial_infective}, "
                f"transmission_rate={args.transmission_rate}, "
                f"simulation_time={args.simulation_time} days")
    
    # Create configuration dictionary
    config = {
        'test_name': args.test_name,
        'mortality': args.mortality,
        'infectivity_period': args.infectivity_period,
        'dt': args.dt,
        'incubation_period': args.incubation_period,
        'total_population': args.total_population,
        'initial_infective': args.initial_infective,
        'transmission_rate': args.transmission_rate,
        'simulation_time': args.simulation_time
    }
    
    # Create SimPy environment
    env = simpy.Environment()
    
    # Create and run simulation
    simulation = SEIRDSimulation(env, config)
    env.process(simulation.run())
    
    # Run the simulation
    logging.info("Running simulation...")
    env.run(until=config['simulation_time'])
    
    # Get final state
    final_state = simulation.get_final_state()
    
    # Output final state as JSONL to stdout
    print(json.dumps(final_state))
    
    logging.info("Simulation completed successfully")


if __name__ == '__main__':
    main()
