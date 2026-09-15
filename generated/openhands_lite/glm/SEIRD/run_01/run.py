#!/usr/bin/env python3
"""
SEIRD Epidemic Compartmental Model Simulation
Uses discrete event simulation (simpy) to model disease spread.
"""

import argparse
import sys
import json
import logging
import simpy


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


class SEIRDModel:
    """SEIRD Epidemic Model using simpy for discrete event simulation."""
    
    def __init__(self, env, args):
        self.env = env
        self.args = args
        
        # Initialize compartments
        self.susceptible = float(args.total_population - args.initial_infective)
        self.exposed = 0.0
        self.infective = float(args.initial_infective)
        self.recovered = 0.0
        self.deceased = 0.0
        
        # Model parameters
        self.beta = args.transmission_rate
        self.N = float(args.total_population)
        self.incubation_period = args.incubation_period
        self.infectivity_period = args.infectivity_period
        self.mortality = args.mortality
        self.dt = args.dt
        
        logging.info(f"Initial state: S={self.susceptible:.2f}, E={self.exposed:.2f}, "
                    f"I={self.infective:.2f}, R={self.recovered:.2f}, D={self.deceased:.2f}")
    
    def update_compartments(self):
        """Update compartment states based on transition rates."""
        # Store old values
        S_old = self.susceptible
        E_old = self.exposed
        I_old = self.infective
        R_old = self.recovered
        D_old = self.deceased
        
        # Calculate transitions
        # S -> E: Susceptible become exposed
        new_exposed = (self.beta * S_old * I_old / self.N) * self.dt
        new_exposed = min(new_exposed, S_old)
        
        # E -> I: Exposed become infectious
        new_infective = (E_old / self.incubation_period) * self.dt
        new_infective = min(new_infective, E_old)
        
        # I -> D: Infective die
        new_deceased = (I_old / self.infectivity_period) * (self.mortality / 100.0) * self.dt
        
        # I -> R: Infective recover
        new_recovered = (I_old / self.infectivity_period) * (1.0 - self.mortality / 100.0) * self.dt
        
        # Update compartments
        self.susceptible = S_old - new_exposed
        self.exposed = E_old + new_exposed - new_infective
        self.infective = I_old + new_infective - new_deceased - new_recovered
        self.recovered = R_old + new_recovered
        self.deceased = D_old + new_deceased
        
        # Verify population conservation
        total = self.susceptible + self.exposed + self.infective + self.recovered + self.deceased
        if abs(total - self.N) > 0.01:
            logging.warning(f"Population conservation warning: {total:.2f} vs {self.N:.2f}")
    
    def simulation_process(self):
        """Main simulation process that updates compartments at each time step."""
        while self.env.now < self.args.simulation_time:
            self.update_compartments()
            logging.debug(f"Time {self.env.now:.2f}: "
                         f"S={self.susceptible:.2f}, E={self.exposed:.2f}, "
                         f"I={self.infective:.2f}, R={self.recovered:.2f}, "
                         f"D={self.deceased:.2f}")
            yield self.env.timeout(self.dt)
    
    def get_final_state(self):
        """Return the final state of all compartments."""
        return {
            "time": round(self.env.now, 2),
            "susceptible": round(self.susceptible, 2),
            "exposed": round(self.exposed, 2),
            "infective": round(self.infective, 2),
            "recovered": round(self.recovered, 2),
            "deceased": round(self.deceased, 2)
        }


def main():
    """Main entry point for the SEIRD simulation."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        stream=sys.stderr
    )
    
    # Parse arguments
    args = parse_arguments()
    
    # Validate arguments
    if args.mortality < 0 or args.mortality > 100:
        logging.error("Mortality rate must be between 0 and 100")
        sys.exit(1)
    
    if args.total_population < 0:
        logging.error("Total population must be non-negative")
        sys.exit(1)
    
    if args.initial_infective < 0 or args.initial_infective > args.total_population:
        logging.error("Initial infective must be between 0 and total population")
        sys.exit(1)
    
    if args.dt <= 0:
        logging.error("Time step (dt) must be positive")
        sys.exit(1)
    
    logging.info(f"Starting SEIRD simulation: {args.test_name}")
    logging.info(f"Parameters: β={args.transmission_rate}, "
                f"incubation={args.incubation_period} days, "
                f"infectivity={args.infectivity_period} days, "
                f"mortality={args.mortality}%, "
                f"dt={args.dt} days, "
                f"simulation_time={args.simulation_time} days")
    
    # Create simpy environment
    env = simpy.Environment()
    
    # Create and run model
    model = SEIRDModel(env, args)
    env.process(model.simulation_process())
    env.run(until=args.simulation_time)
    
    # Output final state
    final_state = model.get_final_state()
    print(json.dumps(final_state))
    
    logging.info(f"Simulation completed at time {final_state['time']:.2f}")
    logging.info(f"Final state: S={final_state['susceptible']}, "
                f"E={final_state['exposed']}, I={final_state['infective']}, "
                f"R={final_state['recovered']}, D={final_state['deceased']}")


if __name__ == '__main__':
    main()
