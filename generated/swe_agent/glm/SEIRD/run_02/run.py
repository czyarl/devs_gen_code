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


def setup_logging() -> None:
    """Configure logging to output to stderr."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        stream=sys.stderr
    )


def parse_arguments() -> argparse.Namespace:
    """
    Parse command line arguments.
    
    Returns:
        argparse.Namespace: Parsed arguments
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


def validate_arguments(args: argparse.Namespace) -> None:
    """
    Validate command line arguments.
    
    Args:
        args: Parsed arguments
        
    Raises:
        ValueError: If arguments are invalid
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
        raise ValueError(f"Total population must be >= 0, got {args.total_population}")
    
    if args.initial_infective < 0:
        raise ValueError(f"Initial infective must be >= 0, got {args.initial_infective}")
    
    if args.initial_infective > args.total_population:
        raise ValueError(
            f"Initial infective ({args.initial_infective}) cannot exceed "
            f"total population ({args.total_population})"
        )
    
    if args.transmission_rate < 0:
        raise ValueError(f"Transmission rate must be >= 0, got {args.transmission_rate}")
    
    if args.simulation_time < 0:
        raise ValueError(f"Simulation time must be >= 0, got {args.simulation_time}")


def simulate_seird(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Run the SEIRD epidemic simulation.
    
    Args:
        args: Parsed command line arguments
        
    Returns:
        Dict containing final state with keys: time, susceptible, exposed, 
        infective, recovered, deceased
    """
    # Extract parameters
    N = args.total_population
    I0 = args.initial_infective
    beta = args.transmission_rate
    incubation_period = args.incubation_period
    infectivity_period = args.infectivity_period
    mortality = args.mortality
    dt = args.dt
    total_time = args.simulation_time
    
    # Initialize compartments
    S = float(N - I0)  # Susceptible
    E = 0.0            # Exposed
    I = float(I0)      # Infective
    R = 0.0            # Recovered
    D = 0.0            # Deceased
    
    logging.info(f"Starting SEIRD simulation for test: {args.test_name}")
    logging.info(f"Parameters: N={N}, I0={I0}, β={beta}, "
                 f"incubation_period={incubation_period}, "
                 f"infectivity_period={infectivity_period}, "
                 f"mortality={mortality}%, dt={dt}, total_time={total_time}")
    logging.info(f"Initial state: S={S:.2f}, E={E:.2f}, I={I:.2f}, R={R:.2f}, D={D:.2f}")
    
    # Handle edge case of zero population
    if N == 0:
        logging.info("Zero population - no simulation needed")
        return {
            "time": round(total_time, 2),
            "susceptible": 0.0,
            "exposed": 0.0,
            "infective": 0.0,
            "recovered": 0.0,
            "deceased": 0.0
        }
    
    # Simulation loop
    t = 0.0
    while t < total_time:
        # Store old values
        S_old = S
        E_old = E
        I_old = I
        R_old = R
        D_old = D
        
        # Calculate transitions
        
        # S -> E: Susceptible individuals become exposed
        # Rate: β * S * I / N per day
        new_exposed = (beta * S_old * I_old / N) * dt
        new_exposed = min(new_exposed, S_old)  # Cannot exceed current susceptible
        
        # E -> I: Exposed individuals become infectious
        # Rate: E / incubation_period per day
        new_infective = (E_old / incubation_period) * dt
        new_infective = min(new_infective, E_old)  # Cannot exceed current exposed
        
        # I -> D: Infective individuals die
        # Rate: I / infectivity_period * (mortality/100) per day
        new_deceased = (I_old / infectivity_period) * (mortality / 100.0) * dt
        
        # I -> R: Infective individuals recover
        # Rate: I / infectivity_period * (1 - mortality/100) per day
        new_recovered = (I_old / infectivity_period) * (1 - mortality / 100.0) * dt
        
        # Update compartments
        S = S_old - new_exposed
        E = E_old + new_exposed - new_infective
        I = I_old + new_infective - new_deceased - new_recovered
        R = R_old + new_recovered
        D = D_old + new_deceased
        
        # Advance time
        t += dt
        
        # Log progress periodically
        if int(t / dt) % 100 == 0:
            logging.debug(f"Time={t:.2f}: S={S:.2f}, E={E:.2f}, I={I:.2f}, R={R:.2f}, D={D:.2f}")
    
    # Ensure we don't exceed total_time
    t = min(t, total_time)
    
    # Verify population conservation
    total = S + E + I + R + D
    logging.info(f"Final state: S={S:.2f}, E={E:.2f}, I={I:.2f}, R={R:.2f}, D={D:.2f}")
    logging.info(f"Total population: {total:.2f} (expected: {N})")
    
    if abs(total - N) > 0.01:
        logging.warning(f"Population conservation check failed: {total:.2f} != {N}")
    
    return {
        "time": round(t, 2),
        "susceptible": round(S, 2),
        "exposed": round(E, 2),
        "infective": round(I, 2),
        "recovered": round(R, 2),
        "deceased": round(D, 2)
    }


def main() -> None:
    """Main entry point for the SEIRD simulation."""
    setup_logging()
    
    try:
        # Parse and validate arguments
        args = parse_arguments()
        validate_arguments(args)
        
        # Run simulation
        result = simulate_seird(args)
        
        # Output final state as JSONL to stdout
        print(json.dumps(result))
        
        logging.info("Simulation completed successfully")
        
    except Exception as e:
        logging.error(f"Error during simulation: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()