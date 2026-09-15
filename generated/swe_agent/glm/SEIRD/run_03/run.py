#!/usr/bin/env python3
"""
SEIRD Epidemic Compartmental Model Simulation

This script simulates infectious disease spread using the SEIRD compartmental model:
- S (Susceptible): Individuals who can be infected
- E (Exposed): Individuals infected but not yet infectious
- I (Infective): Individuals who can transmit the disease
- R (Recovered): Individuals who have recovered and are immune
- D (Deceased): Individuals who have died from the disease
"""

import argparse
import sys
import json
import logging
from typing import Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


class SEIRDSimulator:
    """SEIRD Epidemic Model Simulator"""
    
    def __init__(
        self,
        total_population: int,
        initial_infective: int,
        transmission_rate: float,
        incubation_period: float,
        infectivity_period: float,
        mortality: float,
        dt: float,
        simulation_time: float
    ):
        """
        Initialize the SEIRD simulator.
        
        Args:
            total_population: Total population size (N)
            initial_infective: Initial number of infected individuals (I_0)
            transmission_rate: Transmission rate (β) per day
            incubation_period: Average days from exposure to becoming infectious
            infectivity_period: Average days a person stays infectious
            mortality: Mortality rate as percentage (0-100)
            dt: Time step for numerical integration in days
            simulation_time: Total simulation time in days
        """
        self.total_population = total_population
        self.initial_infective = initial_infective
        self.transmission_rate = transmission_rate
        self.incubation_period = incubation_period
        self.infectivity_period = infectivity_period
        self.mortality = mortality
        self.dt = dt
        self.simulation_time = simulation_time
        
        # Validate inputs
        self._validate_inputs()
        
        # Initialize state variables
        self.susceptible = float(total_population - initial_infective)
        self.exposed = 0.0
        self.infective = float(initial_infective)
        self.recovered = 0.0
        self.deceased = 0.0
        self.current_time = 0.0
        
        logger.info(f"SEIRD Simulator initialized:")
        logger.info(f"  Total Population: {total_population}")
        logger.info(f"  Initial Infective: {initial_infective}")
        logger.info(f"  Transmission Rate: {transmission_rate}")
        logger.info(f"  Incubation Period: {incubation_period} days")
        logger.info(f"  Infectivity Period: {infectivity_period} days")
        logger.info(f"  Mortality: {mortality}%")
        logger.info(f"  Time Step: {dt} days")
        logger.info(f"  Simulation Time: {simulation_time} days")
    
    def _validate_inputs(self):
        """Validate input parameters"""
        if self.total_population < 0:
            raise ValueError("total_population must be >= 0")
        if self.initial_infective < 0:
            raise ValueError("initial_infective must be >= 0")
        if self.initial_infective > self.total_population:
            raise ValueError("initial_infective cannot exceed total_population")
        if self.transmission_rate < 0:
            raise ValueError("transmission_rate must be >= 0")
        if self.incubation_period <= 0:
            raise ValueError("incubation_period must be > 0")
        if self.infectivity_period <= 0:
            raise ValueError("infectivity_period must be > 0")
        if self.mortality < 0 or self.mortality > 100:
            raise ValueError("mortality must be between 0 and 100")
        if self.dt <= 0:
            raise ValueError("dt must be > 0")
        if self.simulation_time < 0:
            raise ValueError("simulation_time must be >= 0")
    
    def step(self) -> Dict[str, Any]:
        """
        Perform one time step of the simulation.
        
        Returns:
            Dictionary containing current state after the step
        """
        # Store old values
        S_old = self.susceptible
        E_old = self.exposed
        I_old = self.infective
        R_old = self.recovered
        D_old = self.deceased
        
        N = self.total_population
        
        # Calculate transitions
        # S -> E: Susceptible individuals become exposed
        if N > 0:
            new_exposed = (self.transmission_rate * S_old * I_old / N) * self.dt
        else:
            new_exposed = 0.0
        new_exposed = min(new_exposed, S_old)
        
        # E -> I: Exposed individuals become infectious
        new_infective = (E_old / self.incubation_period) * self.dt
        new_infective = min(new_infective, E_old)
        
        # I -> D: Infective individuals die
        new_deceased = (I_old / self.infectivity_period) * (self.mortality / 100) * self.dt
        
        # I -> R: Infective individuals recover
        new_recovered = (I_old / self.infectivity_period) * (1 - self.mortality / 100) * self.dt
        
        # Update state variables
        self.susceptible = S_old - new_exposed
        self.exposed = E_old + new_exposed - new_infective
        self.infective = I_old + new_infective - new_deceased - new_recovered
        self.recovered = R_old + new_recovered
        self.deceased = D_old + new_deceased
        
        # Update time
        self.current_time += self.dt
        
        # Return current state
        return {
            "time": round(self.current_time, 2),
            "susceptible": round(self.susceptible, 2),
            "exposed": round(self.exposed, 2),
            "infective": round(self.infective, 2),
            "recovered": round(self.recovered, 2),
            "deceased": round(self.deceased, 2)
        }
    
    def run(self) -> Dict[str, Any]:
        """
        Run the complete simulation.
        
        Returns:
            Dictionary containing final state
        """
        logger.info("Starting simulation...")
        
        steps = int(self.simulation_time / self.dt)
        
        # Initialize state with current values
        state = {
            "time": round(self.current_time, 2),
            "susceptible": round(self.susceptible, 2),
            "exposed": round(self.exposed, 2),
            "infective": round(self.infective, 2),
            "recovered": round(self.recovered, 2),
            "deceased": round(self.deceased, 2)
        }
        
        for i in range(steps):
            state = self.step()
            if i % 100 == 0:
                logger.debug(f"Step {i}/{steps}: {state}")
        
        logger.info("Simulation completed.")
        logger.info(f"Final state: {state}")
        
        # Verify population conservation
        total = self.susceptible + self.exposed + self.infective + self.recovered + self.deceased
        logger.info(f"Population check: {total:.2f} (expected: {self.total_population})")
        
        return state


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="SEIRD Epidemic Compartmental Model Simulation"
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
        help="Mortality rate as percentage (0-100). Default: 10.0"
    )
    
    parser.add_argument(
        "--infectivity_period",
        type=float,
        default=14.0,
        help="Average days a person stays infectious. Default: 14.0"
    )
    
    parser.add_argument(
        "--dt",
        type=float,
        default=0.1,
        help="Time step for numerical integration in days. Default: 0.1"
    )
    
    parser.add_argument(
        "--incubation_period",
        type=float,
        default=5.0,
        help="Average days from exposure to becoming infectious. Default: 5.0"
    )
    
    parser.add_argument(
        "--total_population",
        type=int,
        default=1000,
        help="Total population size. An integer >= 0. Default: 1000"
    )
    
    parser.add_argument(
        "--initial_infective",
        type=int,
        default=10,
        help="Initial number of infected individuals. Default: 10"
    )
    
    parser.add_argument(
        "--transmission_rate",
        type=float,
        default=2.5,
        help="Transmission rate (β) per day. Default: 2.5"
    )
    
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=10.0,
        help="Total simulation time in days. Default: 10.0"
    )
    
    return parser.parse_args()


def main():
    """Main entry point"""
    args = parse_arguments()
    
    logger.info(f"Test case: {args.test_name}")
    
    try:
        # Create and run simulator
        simulator = SEIRDSimulator(
            total_population=args.total_population,
            initial_infective=args.initial_infective,
            transmission_rate=args.transmission_rate,
            incubation_period=args.incubation_period,
            infectivity_period=args.infectivity_period,
            mortality=args.mortality,
            dt=args.dt,
            simulation_time=args.simulation_time
        )
        
        final_state = simulator.run()
        
        # Output final state as JSONL to stdout
        print(json.dumps(final_state))
        
    except Exception as e:
        logger.error(f"Simulation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()