#!/usr/bin/env python3
"""
SEIRD Epidemic Compartmental Model Simulation

This script simulates infectious disease spread using the SEIRD model:
- S: Susceptible
- E: Exposed (infected but not yet infectious)
- I: Infective (infected and can transmit)
- R: Recovered (immune)
- D: Deceased
"""

import argparse
import sys
import json
import logging
import simpy
from typing import Dict, Any


class SEIRDSimulation:
    """SEIRD Epidemic Model Simulation using Discrete Event Simulation"""
    
    def __init__(
        self,
        total_population: int,
        initial_infective: int,
        transmission_rate: float,
        mortality: float,
        infectivity_period: float,
        incubation_period: float,
        dt: float,
        simulation_time: float
    ):
        """
        Initialize the SEIRD simulation.
        
        Args:
            total_population: Total population size (N)
            initial_infective: Initial number of infected individuals (I_0)
            transmission_rate: Transmission rate (β) per day
            mortality: Mortality rate as percentage (0-100)
            infectivity_period: Average days a person stays infectious
            incubation_period: Average days from exposure to becoming infectious
            dt: Time step for numerical integration in days
            simulation_time: Total simulation time in days
        """
        self.N = total_population
        self.I0 = initial_infective
        self.beta = transmission_rate
        self.mortality = mortality
        self.infectivity_period = infectivity_period
        self.incubation_period = incubation_period
        self.dt = dt
        self.simulation_time = simulation_time
        
        # Initialize compartments
        self.S = float(self.N - self.I0)
        self.E = 0.0
        self.I = float(self.I0)
        self.R = 0.0
        self.D = 0.0
        
        # Current simulation time
        self.current_time = 0.0
        
        # Final state
        self.final_state = None
    
    def update_compartments(self) -> None:
        """
        Update compartment states based on transition rates.
        
        Transitions:
        - S → E: β * S * I / N * dt
        - E → I: E / incubation_period * dt
        - I → R: I / infectivity_period * (1 - mortality/100) * dt
        - I → D: I / infectivity_period * (mortality/100) * dt
        """
        # Store old values
        S_old = self.S
        E_old = self.E
        I_old = self.I
        R_old = self.R
        D_old = self.D
        
        # Calculate transitions
        # S → E: Susceptible individuals become exposed
        new_exposed = (self.beta * S_old * I_old / self.N) * self.dt
        new_exposed = min(new_exposed, S_old)  # Cap at available susceptible
        
        # E → I: Exposed individuals become infectious
        new_infective = (E_old / self.incubation_period) * self.dt
        new_infective = min(new_infective, E_old)  # Cap at available exposed
        
        # I → D: Infective individuals die
        new_deceased = (I_old / self.infectivity_period) * (self.mortality / 100.0) * self.dt
        
        # I → R: Infective individuals recover
        new_recovered = (I_old / self.infectivity_period) * (1.0 - self.mortality / 100.0) * self.dt
        
        # Update compartments
        self.S = S_old - new_exposed
        self.E = E_old + new_exposed - new_infective
        self.I = I_old + new_infective - new_deceased - new_recovered
        self.R = R_old + new_recovered
        self.D = D_old + new_deceased
        
        # Ensure non-negative values (floating point precision)
        self.S = max(0.0, self.S)
        self.E = max(0.0, self.E)
        self.I = max(0.0, self.I)
        self.R = max(0.0, self.R)
        self.D = max(0.0, self.D)
    
    def run(self, env: simpy.Environment) -> None:
        """
        Run the simulation using simpy environment.
        
        Args:
            env: SimPy environment
        """
        logging.info(f"Starting SEIRD simulation at time {self.current_time:.2f}")
        logging.info(f"Initial state: S={self.S:.2f}, E={self.E:.2f}, I={self.I:.2f}, R={self.R:.2f}, D={self.D:.2f}")
        
        while self.current_time < self.simulation_time:
            # Update compartments
            self.update_compartments()
            
            # Advance time
            self.current_time += self.dt
            
            # Log progress periodically
            if int(self.current_time / self.dt) % 10 == 0:
                logging.debug(
                    f"Time {self.current_time:.2f}: "
                    f"S={self.S:.2f}, E={self.E:.2f}, I={self.I:.2f}, "
                    f"R={self.R:.2f}, D={self.D:.2f}"
                )
        
        # Store final state
        self.final_state = {
            "time": round(self.current_time, 2),
            "susceptible": round(self.S, 2),
            "exposed": round(self.E, 2),
            "infective": round(self.I, 2),
            "recovered": round(self.R, 2),
            "deceased": round(self.D, 2)
        }
        
        logging.info(f"Simulation completed at time {self.current_time:.2f}")
        logging.info(f"Final state: S={self.S:.2f}, E={self.E:.2f}, I={self.I:.2f}, R={self.R:.2f}, D={self.D:.2f}")
        
        # Verify population conservation
        total = self.S + self.E + self.I + self.R + self.D
        logging.info(f"Population check: {total:.2f} / {self.N} (difference: {abs(total - self.N):.6f})")
    
    def get_final_state(self) -> Dict[str, Any]:
        """Get the final simulation state."""
        return self.final_state


def parse_arguments() -> argparse.Namespace:
    """
    Parse command line arguments.
    
    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        description="SEIRD Epidemic Compartmental Model Simulation",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument(
        "--test_name",
        type=str,
        required=True,
        help="Name of the test case being run"
    )
    
    parser.add_argument(
        "--mortality",
        type=float,
        default=10.0,
        help="Mortality rate as percentage (0-100)"
    )
    
    parser.add_argument(
        "--infectivity_period",
        type=float,
        default=14.0,
        help="Average days a person stays infectious"
    )
    
    parser.add_argument(
        "--dt",
        type=float,
        default=0.1,
        help="Time step for numerical integration in days"
    )
    
    parser.add_argument(
        "--incubation_period",
        type=float,
        default=5.0,
        help="Average days from exposure to becoming infectious"
    )
    
    parser.add_argument(
        "--total_population",
        type=int,
        default=1000,
        help="Total population size (integer >= 0)"
    )
    
    parser.add_argument(
        "--initial_infective",
        type=int,
        default=10,
        help="Initial number of infected individuals"
    )
    
    parser.add_argument(
        "--transmission_rate",
        type=float,
        default=2.5,
        help="Transmission rate (β) per day"
    )
    
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=10.0,
        help="Total simulation time in days"
    )
    
    return parser.parse_args()


def main() -> None:
    """Main entry point for the SEIRD simulation."""
    # Parse command line arguments
    args = parse_arguments()
    
    # Setup logging to stderr
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        stream=sys.stderr
    )
    
    logging.info(f"Test case: {args.test_name}")
    logging.info(f"Configuration:")
    logging.info(f"  Total population: {args.total_population}")
    logging.info(f"  Initial infective: {args.initial_infective}")
    logging.info(f"  Transmission rate (β): {args.transmission_rate}")
    logging.info(f"  Mortality: {args.mortality}%")
    logging.info(f"  Infectivity period: {args.infectivity_period} days")
    logging.info(f"  Incubation period: {args.incubation_period} days")
    logging.info(f"  Time step (dt): {args.dt} days")
    logging.info(f"  Simulation time: {args.simulation_time} days")
    
    # Validate inputs
    if args.total_population < 0:
        logging.error("Total population must be >= 0")
        sys.exit(1)
    
    if args.initial_infective > args.total_population:
        logging.error("Initial infective cannot exceed total population")
        sys.exit(1)
    
    if args.mortality < 0 or args.mortality > 100:
        logging.error("Mortality must be between 0 and 100")
        sys.exit(1)
    
    if args.dt <= 0:
        logging.error("Time step (dt) must be positive")
        sys.exit(1)
    
    # Create simulation instance
    simulation = SEIRDSimulation(
        total_population=args.total_population,
        initial_infective=args.initial_infective,
        transmission_rate=args.transmission_rate,
        mortality=args.mortality,
        infectivity_period=args.infectivity_period,
        incubation_period=args.incubation_period,
        dt=args.dt,
        simulation_time=args.simulation_time
    )
    
    # Create simpy environment and run simulation
    env = simpy.Environment()
    env.process(simulation.run(env))
    env.run()
    
    # Output final state as JSONL to stdout
    final_state = simulation.get_final_state()
    if final_state:
        print(json.dumps(final_state))
    else:
        logging.error("Simulation failed to produce final state")
        sys.exit(1)


if __name__ == "__main__":
    main()
