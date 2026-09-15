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


def seird_model_process(env, args, state):
    """
    Simpy process that updates SEIRD compartments at each time step.
    
    Args:
        env: Simpy environment
        args: Parsed command line arguments
        state: Dictionary containing current compartment values
    """
    while env.now < args.simulation_time:
        # Current state
        S = state['susceptible']
        E = state['exposed']
        I = state['infective']
        R = state['recovered']
        D = state['deceased']
        N = args.total_population
        
        # Calculate transitions
        # S -> E: Susceptible become exposed
        new_exposed = (args.transmission_rate * S * I / N) * args.dt
        new_exposed = min(new_exposed, S)
        
        # E -> I: Exposed become infectious
        new_infective = (E / args.incubation_period) * args.dt
        new_infective = min(new_infective, E)
        
        # I -> D: Infective die
        new_deceased = (I / args.infectivity_period) * (args.mortality / 100) * args.dt
        
        # I -> R: Infective recover
        new_recovered = (I / args.infectivity_period) * (1 - args.mortality / 100) * args.dt
        
        # Update compartments
        state['susceptible'] = S - new_exposed
        state['exposed'] = E + new_exposed - new_infective
        state['infective'] = I + new_infective - new_deceased - new_recovered
        state['recovered'] = R + new_recovered
        state['deceased'] = D + new_deceased
        
        # Log current state to stderr
        logging.debug(
            f"Time: {env.now:.2f}, S: {state['susceptible']:.2f}, "
            f"E: {state['exposed']:.2f}, I: {state['infective']:.2f}, "
            f"R: {state['recovered']:.2f}, D: {state['deceased']:.2f}"
        )
        
        # Wait for next time step
        yield env.timeout(args.dt)


def run_simulation(args):
    """
    Run the SEIRD simulation using simpy.
    
    Args:
        args: Parsed command line arguments
    
    Returns:
        Dictionary containing final state
    """
    # Initialize state
    state = {
        'susceptible': float(args.total_population - args.initial_infective),
        'exposed': 0.0,
        'infective': float(args.initial_infective),
        'recovered': 0.0,
        'deceased': 0.0
    }
    
    # Create simpy environment
    env = simpy.Environment()
    
    # Add the SEIRD model process
    env.process(seird_model_process(env, args, state))
    
    # Run simulation
    logging.info(f"Starting simulation: {args.test_name}")
    logging.info(f"Total population: {args.total_population}")
    logging.info(f"Initial infective: {args.initial_infective}")
    logging.info(f"Simulation time: {args.simulation_time} days")
    logging.info(f"Time step (dt): {args.dt} days")
    
    env.run(until=args.simulation_time)
    
    logging.info("Simulation completed")
    
    return state


def main():
    """Main entry point."""
    # Setup logging to stderr
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        stream=sys.stderr
    )
    
    # Parse arguments
    args = parse_arguments()
    
    # Validate arguments
    if args.mortality < 0 or args.mortality > 100:
        logging.error("Mortality must be between 0 and 100")
        sys.exit(1)
    
    if args.total_population < 0:
        logging.error("Total population must be >= 0")
        sys.exit(1)
    
    if args.initial_infective < 0:
        logging.error("Initial infective must be >= 0")
        sys.exit(1)
    
    if args.initial_infective > args.total_population:
        logging.error("Initial infective cannot exceed total population")
        sys.exit(1)
    
    if args.dt <= 0:
        logging.error("Time step (dt) must be > 0")
        sys.exit(1)
    
    if args.simulation_time <= 0:
        logging.error("Simulation time must be > 0")
        sys.exit(1)
    
    # Run simulation
    final_state = run_simulation(args)
    
    # Output final state as JSONL to stdout
    output = {
        'time': round(args.simulation_time, 2),
        'susceptible': round(final_state['susceptible'], 2),
        'exposed': round(final_state['exposed'], 2),
        'infective': round(final_state['infective'], 2),
        'recovered': round(final_state['recovered'], 2),
        'deceased': round(final_state['deceased'], 2)
    }
    
    print(json.dumps(output))
    
    # Verify population conservation
    total = (final_state['susceptible'] + final_state['exposed'] + 
             final_state['infective'] + final_state['recovered'] + 
             final_state['deceased'])
    logging.info(f"Final total population: {total:.2f} (expected: {args.total_population})")


if __name__ == '__main__':
    main()