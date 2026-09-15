#!/usr/bin/env python3
"""
SEIRD Epidemic Compartmental Model Simulation
============================================

This script simulates infectious disease spread in a closed population using
the SEIRD (Susceptible-Exposed-Infective-Recovered-Deceased) compartmental model.

The model includes:
- S (Susceptible): Individuals who can be infected
- E (Exposed): Individuals who are infected but not yet infectious
- I (Infective): Individuals who are infected and can transmit the disease
- R (Recovered): Individuals who have recovered and are immune
- D (Deceased): Individuals who have died from the disease

Model Characteristics:
- Homogeneous Mixing: All individuals have equal contact probability
- Closed Population: No births, deaths (other than disease), or migration
- Discrete-Time: State updates occur at fixed time intervals (dt)
"""

import argparse
import json
import logging
import sys


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='SEIRD Epidemic Model Simulation')
    
    parser.add_argument('--test_name', type=str, required=True,
                        help='Name of the test case being run')
    
    parser.add_argument('--mortality', type=float, default=10.0,
                        help='Mortality rate as percentage (0-100). Default: 10.0')
    
    parser.add_argument('--infectivity_period', type=float, default=14.0,
                        help='Average days a person stays infectious. Default: 14.0')
    
    parser.add_argument('--dt', type=float, default=0.1,
                        help='Time step for numerical integration in days. Default: 0.1')
    
    parser.add_argument('--incubation_period', type=float, default=5.0,
                        help='Average days from exposure to becoming infectious. Default: 5.0')
    
    parser.add_argument('--total_population', type=int, default=1000,
                        help='Total population size. Default: 1000')
    
    parser.add_argument('--initial_infective', type=int, default=10,
                        help='Initial number of infected individuals. Default: 10')
    
    parser.add_argument('--transmission_rate', type=float, default=2.5,
                        help='Transmission rate (β) per day. Default: 2.5')
    
    parser.add_argument('--simulation_time', type=float, default=10.0,
                        help='Total simulation time in days. Default: 10.0')
    
    return parser.parse_args()


def simulate_seird(total_population, initial_infective, transmission_rate,
                   infectivity_period, incubation_period, mortality_rate, dt, simulation_time):
    """
    Simulate SEIRD model using discrete time steps.
    
    Args:
        total_population: Total population size
        initial_infective: Initial number of infected individuals
        transmission_rate: Transmission rate (β) per day
        infectivity_period: Average days a person stays infectious
        incubation_period: Average days from exposure to becoming infectious
        mortality_rate: Mortality rate as percentage (0-100)
        dt: Time step for numerical integration in days
        simulation_time: Total simulation time in days
    
    Returns:
        Dictionary with final compartment values
    """
    # Initialize compartments
    susceptible = total_population - initial_infective
    exposed = 0
    infective = initial_infective
    recovered = 0
    deceased = 0
    
    # Store compartment history for debugging
    history = []
    
    # Simulation loop
    current_time = 0.0
    while current_time < simulation_time:
        # Calculate transitions for this time step
        # Calculate new exposed individuals
        if susceptible > 0 and infective > 0:
            new_exposed = (transmission_rate * susceptible * infective / 
                          total_population) * dt
            # Cut the value to not exceed susceptible population
            new_exposed = min(new_exposed, susceptible)
        else:
            new_exposed = 0
        
        # Calculate new infective individuals (from exposed)
        if exposed > 0:
            new_infective = (exposed / incubation_period) * dt
            # Cut the value to not exceed exposed population
            new_infective = min(new_infective, exposed)
        else:
            new_infective = 0
        
        # Calculate new recovered and deceased individuals (from infective)
        if infective > 0:
            new_deceased = (infective / infectivity_period) * (mortality_rate / 100.0) * dt
            new_recovered = (infective / infectivity_period) * (1 - mortality_rate / 100.0) * dt
        else:
            new_deceased = 0
            new_recovered = 0
        
        # Update compartments
        susceptible -= new_exposed
        exposed += new_exposed - new_infective
        infective += new_infective - new_deceased - new_recovered
        recovered += new_recovered
        deceased += new_deceased
        
        # Ensure no negative values
        susceptible = max(0, susceptible)
        exposed = max(0, exposed)
        infective = max(0, infective)
        recovered = max(0, recovered)
        deceased = max(0, deceased)
        
        # Store history for debugging
        history.append({
            'time': current_time,
            'susceptible': susceptible,
            'exposed': exposed,
            'infective': infective,
            'recovered': recovered,
            'deceased': deceased
        })
        
        # Log current state every day (or when we're at a day boundary)
        if current_time % 1.0 < dt or abs(current_time - simulation_time) < dt:
            logging.debug(f"Time {current_time:.2f}: S={susceptible:.2f}, "
                          f"E={exposed:.2f}, I={infective:.2f}, "
                          f"R={recovered:.2f}, D={deceased:.2f}")
        
        # Move to next time step
        current_time += dt
    
    return {
        "time": round(simulation_time, 2),
        "susceptible": round(susceptible, 2),
        "exposed": round(exposed, 2),
        "infective": round(infective, 2),
        "recovered": round(recovered, 2),
        "deceased": round(deceased, 2)
    }


def main():
    """Main function to run the SEIRD simulation."""
    # Parse arguments
    args = parse_args()
    
    # Set up logging
    logging.basicConfig(level=logging.DEBUG, 
                       format='%(asctime)s - %(levelname)s - %(message)s',
                       stream=sys.stderr)
    
    logging.info(f"Starting SEIRD simulation for test: {args.test_name}")
    logging.info(f"Parameters: {vars(args)}")
    
    # Run simulation
    final_state = simulate_seird(
        total_population=args.total_population,
        initial_infective=args.initial_infective,
        transmission_rate=args.transmission_rate,
        infectivity_period=args.infectivity_period,
        incubation_period=args.incubation_period,
        mortality_rate=args.mortality,
        dt=args.dt,
        simulation_time=args.simulation_time
    )
    
    # Print final state to stdout as JSONL
    print(json.dumps(final_state))
    
    # Log final state
    logging.info(f"Final state: {final_state}")


if __name__ == "__main__":
    main()