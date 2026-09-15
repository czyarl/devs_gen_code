#!/usr/bin/env python3
"""
SEIRD Epidemic Compartmental Model Simulation
Uses discrete event simulation to model infectious disease spread.
"""

import argparse
import sys
import json
import logging
from collections import namedtuple
import simpy

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

# State container for SEIRD compartments
SEIRDState = namedtuple('SEIRDState', ['susceptible', 'exposed', 'infective', 'recovered', 'deceased'])


class SEIRDSimulation:
    """SEIRD epidemic model using discrete event simulation."""
    
    def __init__(self, env, total_population, initial_infective, transmission_rate,
                 incubation_period, infectivity_period, mortality, dt):
        """
        Initialize the SEIRD simulation.
        
        Args:
            env: SimPy environment
            total_population: Total population size
            initial_infective: Initial number of infected individuals
            transmission_rate: Transmission rate (β) per day
            incubation_period: Average days from exposure to becoming infectious
            infectivity_period: Average days a person stays infectious
            mortality: Mortality rate as percentage (0-100)
            dt: Time step for numerical integration in days
        """
        self.env = env
        self.total_population = total_population
        self.transmission_rate = transmission_rate
        self.incubation_period = incubation_period
        self.infectivity_period = infectivity_period
        self.mortality = mortality
        self.dt = dt
        
        # Initialize compartments
        self.susceptible = total_population - initial_infective
        self.exposed = 0.0
        self.infective = float(initial_infective)
        self.recovered = 0.0
        self.deceased = 0.0
        
        # Track final state
        self.final_state = None
        
        logger.info(f"Initialized SEIRD simulation:")
        logger.info(f"  Total Population: {total_population}")
        logger.info(f"  Initial Infective: {initial_infective}")
        logger.info(f"  Transmission Rate: {transmission_rate}")
        logger.info(f"  Incubation Period: {incubation_period} days")
        logger.info(f"  Infectivity Period: {infectivity_period} days")
        logger.info(f"  Mortality: {mortality}%")
        logger.info(f"  Time Step: {dt} days")
    
    def update_state(self):
        """Update SEIRD compartments based on transition rates."""
        # Store old values
        S_old = self.susceptible
        E_old = self.exposed
        I_old = self.infective
        R_old = self.recovered
        D_old = self.deceased
        N = self.total_population
        
        # Calculate transitions
        # S -> E: Susceptible individuals become exposed
        new_exposed = (self.transmission_rate * S_old * I_old / N) * self.dt
        new_exposed = min(new_exposed, S_old)
        
        # E -> I: Exposed individuals become infectious
        new_infective = (E_old / self.incubation_period) * self.dt
        new_infective = min(new_infective, E_old)
        
        # I -> D: Infective individuals die
        new_deceased = (I_old / self.infectivity_period) * (self.mortality / 100) * self.dt
        
        # I -> R: Infective individuals recover
        new_recovered = (I_old / self.infectivity_period) * (1 - self.mortality / 100) * self.dt
        
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
        
        # Verify population conservation
        total = self.susceptible + self.exposed + self.infective + self.recovered + self.deceased
        if abs(total - self.total_population) > 0.01:
            logger.warning(f"Population conservation check: {total:.2f} vs {self.total_population}")
    
    def run(self, simulation_time):
        """
        Run the simulation for the specified time.
        
        Args:
            simulation_time: Total simulation time in days
        """
        logger.info(f"Starting simulation for {simulation_time} days")
        
        # Run simulation using discrete time steps
        current_time = 0.0
        while current_time < simulation_time:
            self.update_state()
            current_time += self.dt
            yield self.env.timeout(self.dt)
        
        # Store final state
        self.final_state = SEIRDState(
            susceptible=round(self.susceptible, 2),
            exposed=round(self.exposed, 2),
            infective=round(self.infective, 2),
            recovered=round(self.recovered, 2),
            deceased=round(self.deceased, 2)
        )
        
        logger.info(f"Simulation completed at time {simulation_time}")
        logger.info(f"Final state: S={self.final_state.susceptible}, "
                   f"E={self.final_state.exposed}, I={self.final_state.infective}, "
                   f"R={self.final_state.recovered}, D={self.final_state.deceased}")


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
        help='Total population size (integer >= 0)'
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
    
    # Validate arguments
    if args.total_population < 0:
        logger.error("total_population must be >= 0")
        sys.exit(1)
    
    if args.initial_infective > args.total_population:
        logger.error("initial_infective cannot exceed total_population")
        sys.exit(1)
    
    if args.mortality < 0 or args.mortality > 100:
        logger.error("mortality must be between 0 and 100")
        sys.exit(1)
    
    if args.dt <= 0:
        logger.error("dt must be positive")
        sys.exit(1)
    
    logger.info(f"Test case: {args.test_name}")
    
    # Create SimPy environment
    env = simpy.Environment()
    
    # Create and run simulation
    simulation = SEIRDSimulation(
        env=env,
        total_population=args.total_population,
        initial_infective=args.initial_infective,
        transmission_rate=args.transmission_rate,
        incubation_period=args.incubation_period,
        infectivity_period=args.infectivity_period,
        mortality=args.mortality,
        dt=args.dt
    )
    
    env.process(simulation.run(args.simulation_time))
    env.run()
    
    # Output final state as JSONL
    output = {
        "time": round(args.simulation_time, 2),
        "susceptible": simulation.final_state.susceptible,
        "exposed": simulation.final_state.exposed,
        "infective": simulation.final_state.infective,
        "recovered": simulation.final_state.recovered,
        "deceased": simulation.final_state.deceased
    }
    
    print(json.dumps(output))
    
    logger.info("Simulation finished successfully")


if __name__ == '__main__':
    main()