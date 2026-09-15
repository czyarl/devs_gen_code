#!/usr/bin/env python3
"""
SEIRD Epidemic Compartmental Model Simulation
Uses Discrete Event Simulation (simpy) to model disease spread.
"""

import argparse
import sys
import json
import logging
import simpy


class SEIRDSimulation:
    """SEIRD Epidemic Model using Discrete Event Simulation."""
    
    def __init__(self, env, total_population, initial_infective, transmission_rate,
                 incubation_period, infectivity_period, mortality, dt):
        """
        Initialize the SEIRD simulation.
        
        Args:
            env: SimPy environment
            total_population: Total population size (N)
            initial_infective: Initial number of infected individuals (I_0)
            transmission_rate: Transmission rate (β) per day
            incubation_period: Average days from exposure to becoming infectious
            infectivity_period: Average days a person stays infectious
            mortality: Mortality rate as percentage (0-100)
            dt: Time step for numerical integration in days
        """
        self.env = env
        self.N = total_population
        self.beta = transmission_rate
        self.incubation_period = incubation_period
        self.infectivity_period = infectivity_period
        self.mortality = mortality
        self.dt = dt
        
        # Initialize compartments
        self.S = float(total_population - initial_infective)
        self.E = 0.0
        self.I = float(initial_infective)
        self.R = 0.0
        self.D = 0.0
        
        # Store history for debugging
        self.history = []
        
    def update_state(self):
        """Update the SEIRD compartments based on transition rates."""
        # Store old values
        S_old = self.S
        E_old = self.E
        I_old = self.I
        R_old = self.R
        D_old = self.D
        
        # Calculate transitions
        # S → E: Susceptible individuals become exposed
        new_exposed = (self.beta * S_old * I_old / self.N) * self.dt
        new_exposed = min(new_exposed, S_old)
        
        # E → I: Exposed individuals become infectious
        new_infective = (E_old / self.incubation_period) * self.dt
        new_infective = min(new_infective, E_old)
        
        # I → D: Infective individuals die
        new_deceased = (I_old / self.infectivity_period) * (self.mortality / 100.0) * self.dt
        
        # I → R: Infective individuals recover
        new_recovered = (I_old / self.infectivity_period) * (1 - self.mortality / 100.0) * self.dt
        
        # Update compartments
        self.S = S_old - new_exposed
        self.E = E_old + new_exposed - new_infective
        self.I = I_old + new_infective - new_deceased - new_recovered
        self.R = R_old + new_recovered
        self.D = D_old + new_deceased
        
        # Store history
        self.history.append({
            'time': self.env.now,
            'S': self.S,
            'E': self.E,
            'I': self.I,
            'R': self.R,
            'D': self.D
        })
        
        logging.debug(f"Time {self.env.now:.2f}: S={self.S:.2f}, E={self.E:.2f}, "
                     f"I={self.I:.2f}, R={self.R:.2f}, D={self.D:.2f}")
    
    def run(self, simulation_time):
        """Run the simulation for the specified time."""
        while self.env.now < simulation_time:
            self.update_state()
            # Advance time by dt
            yield self.env.timeout(self.dt)
        
        # Final update at exact simulation time
        if self.env.now > simulation_time:
            # We overshot, need to adjust
            # The last step was too large, so we need to recalculate
            # For simplicity, we'll just use the last state
            pass


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
        help='Total population size. Default: 1000'
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


def main():
    """Main entry point for the SEIRD simulation."""
    # Parse command line arguments
    args = parse_arguments()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        stream=sys.stderr
    )
    
    logging.info(f"Starting SEIRD simulation: {args.test_name}")
    logging.info(f"Parameters: N={args.total_population}, I0={args.initial_infective}, "
                f"β={args.transmission_rate}, incubation={args.incubation_period}, "
                f"infectivity={args.infectivity_period}, mortality={args.mortality}%, "
                f"dt={args.dt}, T={args.simulation_time}")
    
    # Validate arguments
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
    
    # Create SimPy environment
    env = simpy.Environment()
    
    # Create simulation instance
    sim = SEIRDSimulation(
        env=env,
        total_population=args.total_population,
        initial_infective=args.initial_infective,
        transmission_rate=args.transmission_rate,
        incubation_period=args.incubation_period,
        infectivity_period=args.infectivity_period,
        mortality=args.mortality,
        dt=args.dt
    )
    
    # Run the simulation
    env.process(sim.run(args.simulation_time))
    env.run()
    
    # Verify population conservation
    total = sim.S + sim.E + sim.I + sim.R + sim.D
    logging.info(f"Population conservation check: {total:.2f} (expected: {args.total_population})")
    
    # Output final state as JSONL
    result = {
        "time": round(env.now, 2),
        "susceptible": round(sim.S, 2),
        "exposed": round(sim.E, 2),
        "infective": round(sim.I, 2),
        "recovered": round(sim.R, 2),
        "deceased": round(sim.D, 2)
    }
    
    print(json.dumps(result))
    
    logging.info(f"Simulation completed. Final time: {env.now:.2f} days")


if __name__ == "__main__":
    main()