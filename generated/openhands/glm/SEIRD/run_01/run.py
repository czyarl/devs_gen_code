#!/usr/bin/env python3
"""
SEIRD Epidemic Compartmental Model Simulation
Uses discrete event simulation (simpy) to model disease spread.
"""

import argparse
import sys
import json
import logging
from collections import namedtuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


class SEIRDModel:
    """SEIRD Epidemic Model using Discrete Event Simulation."""
    
    def __init__(self, env, params):
        """
        Initialize the SEIRD model.
        
        Args:
            env: SimPy environment
            params: NamedTuple with model parameters
        """
        self.env = env
        self.params = params
        
        # Initialize compartments
        self.susceptible = float(params.total_population - params.initial_infective)
        self.exposed = 0.0
        self.infective = float(params.initial_infective)
        self.recovered = 0.0
        self.deceased = 0.0
        
        # Track state changes
        self.state_history = []
        
        logger.info(f"Initial state - S: {self.susceptible:.2f}, E: {self.exposed:.2f}, "
                   f"I: {self.infective:.2f}, R: {self.recovered:.2f}, D: {self.deceased:.2f}")
    
    def update_state(self):
        """Update compartment states based on transition rates."""
        # Current state
        S_old = self.susceptible
        E_old = self.exposed
        I_old = self.infective
        R_old = self.recovered
        D_old = self.deceased
        
        N = self.params.total_population
        dt = self.params.dt
        beta = self.params.transmission_rate
        incubation = self.params.incubation_period
        infectivity = self.params.infectivity_period
        mortality = self.params.mortality
        
        # Calculate transitions
        # S -> E: Susceptible become exposed
        new_exposed = (beta * S_old * I_old / N) * dt
        new_exposed = min(new_exposed, S_old)
        
        # E -> I: Exposed become infectious
        new_infective = (E_old / incubation) * dt
        new_infective = min(new_infective, E_old)
        
        # I -> D: Infective die
        new_deceased = (I_old / infectivity) * (mortality / 100.0) * dt
        
        # I -> R: Infective recover
        new_recovered = (I_old / infectivity) * (1.0 - mortality / 100.0) * dt
        
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
        
        # Log state update
        logger.debug(f"Time {self.env.now:.2f}: S={self.susceptible:.2f}, "
                    f"E={self.exposed:.2f}, I={self.infective:.2f}, "
                    f"R={self.recovered:.2f}, D={self.deceased:.2f}")
    
    def simulation_process(self):
        """Main simulation process."""
        while self.env.now < self.params.simulation_time:
            # Update state at each time step
            self.update_state()
            
            # Wait for next time step
            yield self.env.timeout(self.params.dt)
        
        # Final update to ensure we capture the last state
        self.update_state()
        
        logger.info(f"Simulation completed at time {self.env.now:.2f}")
    
    def get_final_state(self):
        """Return the final state as a dictionary."""
        total = (self.susceptible + self.exposed + self.infective + 
                self.recovered + self.deceased)
        
        logger.info(f"Final population check: {total:.2f} (expected: {self.params.total_population})")
        
        return {
            "time": round(self.env.now, 2),
            "susceptible": round(self.susceptible, 2),
            "exposed": round(self.exposed, 2),
            "infective": round(self.infective, 2),
            "recovered": round(self.recovered, 2),
            "deceased": round(self.deceased, 2)
        }


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
    
    return parser.parse_args()


def validate_arguments(args):
    """Validate command line arguments."""
    if args.mortality < 0 or args.mortality > 100:
        raise ValueError("Mortality must be between 0 and 100")
    
    if args.infectivity_period <= 0:
        raise ValueError("Infectivity period must be positive")
    
    if args.dt <= 0:
        raise ValueError("Time step (dt) must be positive")
    
    if args.incubation_period <= 0:
        raise ValueError("Incubation period must be positive")
    
    if args.total_population < 0:
        raise ValueError("Total population must be non-negative")
    
    if args.initial_infective < 0:
        raise ValueError("Initial infective must be non-negative")
    
    if args.initial_infective > args.total_population:
        raise ValueError("Initial infective cannot exceed total population")
    
    if args.transmission_rate < 0:
        raise ValueError("Transmission rate must be non-negative")
    
    if args.simulation_time < 0:
        raise ValueError("Simulation time must be non-negative")


def main():
    """Main entry point for the simulation."""
    try:
        # Parse and validate arguments
        args = parse_arguments()
        validate_arguments(args)
        
        logger.info(f"Starting SEIRD simulation: {args.test_name}")
        logger.info(f"Parameters: mortality={args.mortality}%, "
                   f"infectivity_period={args.infectivity_period} days, "
                   f"dt={args.dt} days, "
                   f"incubation_period={args.incubation_period} days, "
                   f"total_population={args.total_population}, "
                   f"initial_infective={args.initial_infective}, "
                   f"transmission_rate={args.transmission_rate}, "
                   f"simulation_time={args.simulation_time} days")
        
        # Create named tuple for parameters
        Params = namedtuple('Params', [
            'test_name', 'mortality', 'infectivity_period', 'dt',
            'incubation_period', 'total_population', 'initial_infective',
            'transmission_rate', 'simulation_time'
        ])
        
        params = Params(
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
        
        # Import simpy
        import simpy
        
        # Create simulation environment
        env = simpy.Environment()
        
        # Create and run the model
        model = SEIRDModel(env, params)
        env.process(model.simulation_process())
        env.run()
        
        # Output final state as JSONL
        final_state = model.get_final_state()
        print(json.dumps(final_state))
        
        logger.info("Simulation completed successfully")
        
    except Exception as e:
        logger.error(f"Simulation failed: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()