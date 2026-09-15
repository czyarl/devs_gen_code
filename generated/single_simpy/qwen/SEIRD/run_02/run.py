```python
#!/usr/bin/env python3
import argparse
import sys
import json
import logging
import random

def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(description='SEIRD Epidemic Simulation')
    
    parser.add_argument('--test_name', type=str, required=True, help='Name of the test case being run')
    parser.add_argument('--mortality', type=float, default=10.0, help='Mortality rate as percentage (0-100)')
    parser.add_argument('--infectivity_period', type=float, default=14.0, help='Average days a person stays infectious')
    parser.add_argument('--dt', type=float, default=0.1, help='Time step for numerical integration in days')
    parser.add_argument('--incubation_period', type=float, default=5.0, help='Average days from exposure to becoming infectious')
    parser.add_argument('--total_population', type=int, default=1000, help='Total population size')
    parser.add_argument('--initial_infective', type=int, default=10, help='Initial number of infected individuals')
    parser.add_argument('--transmission_rate', type=float, default=2.5, help='Transmission rate (β) per day')
    parser.add_argument('--simulation_time', type=float, default=10.0, help='Total simulation time in days')
    
    # Parse arguments
    args = parser.parse_args()
    
    # Validate inputs
    if args.total_population < 0:
        print(f"Error: total_population must be >= 0", file=sys.stderr)
        sys.exit(1)
    
    if args.initial_infective < 0:
        print(f"Error: initial_infective must be >= 0", file=sys.stderr)
        sys.exit(1)
    
    if args.initial_infective > args.total_population:
        print(f"Error: initial_infective cannot exceed total_population", file=sys.stderr)
        sys.exit(1)
    
    if args.mortality < 0 or args.mortality > 100:
        print(f"Error: mortality must be between 0 and 100", file=sys.stderr)
        sys.exit(1)
    
    if args.dt <= 0:
        print(f"Error: dt must be positive", file=sys.stderr)
        sys.exit(1)
    
    if args.simulation_time <= 0:
        print(f"Error: simulation_time must be positive", file=sys.stderr)
        sys.exit(1)
    
    # Set up logging
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Initialize population compartments
    S = args.total_population - args.initial_infective
    E = 0
    I = args.initial_infective
    R = 0
    D = 0
    
    # Validate population conservation
    if S + E + I + R + D != args.total_population:
        print(f"Error: Initial population does not sum to total_population", file=sys.stderr)
        sys.exit(1)
    
    # Simulation parameters
    dt = args.dt
    total_time = args.simulation_time
    beta = args.transmission_rate
    N = args.total_population
    incubation_period = args.incubation_period
    infectivity_period = args.infectivity_period
    mortality_rate = args.mortality / 100.0
    
    # Log initial state
    logging.info(f"Starting simulation: {args.test_name}")
    logging.info(f"Parameters: dt={dt}, total_time={total_time}, beta={beta}, N={N}")
    logging.info(f"Initial state: S={S}, E={E}, I={I}, R={R}, D={D}")
    
    # Simulation loop
    current_time = 0.0
    steps = int(total_time / dt)
    
    # We'll simulate step by step
    for step in range(steps):
        # Calculate transitions
        # S -> E: new_exposed = (β * S * I / N) * dt
        new_exposed = (beta * S * I / N) * dt
        new_exposed = min(new_exposed, S)  # Cannot expose more than susceptible
        
        # E -> I: new_infective = (E / incubation_period) * dt
        new_infective = (E / incubation_period) * dt
        new_infective = min(new_infective, E)  # Cannot infect more than exposed
        
        # I -> R and I -> D
        # new_recovered = (I / infectivity_period) * (1 - mortality_rate) * dt
        # new_deceased = (I / infectivity_period) * mortality_rate * dt
        new_recovered = (I / infectivity_period) * (1 - mortality_rate) * dt
        new_deceased = (I / infectivity_period) * mortality_rate * dt
        
        # Ensure we don't recover or kill more than currently infective
        total_outflow = new_recovered + new_deceased
        if total_outflow > I:
            # Scale proportionally
            scale_factor = I / total_outflow
            new_recovered *= scale_factor
            new_deceased *= scale_factor
        
        # Update compartments
        S_new = S - new_exposed
        E_new = E + new_exposed - new_infective
        I_new = I + new_infective - new_recovered - new_deceased
        R_new = R + new_recovered
        D_new = D + new_deceased
        
        # Ensure non-negative values (floating point errors)
        S_new = max(0, S_new)
        E_new = max(0, E_new)
        I_new = max(0, I_new)
        R_new = max(0, R_new)
        D_new = max(0, D_new)
        
        # Update for next iteration
        S, E, I, R, D = S_new, E_new, I_new, R_new, D_new
        
        current_time += dt
        
        # Log progress every 10% of simulation
        if step % max(1, steps // 10) == 0:
            logging.info(f"Time: {current_time:.2f} days | S: {S:.2f}, E: {E:.2f}, I: {I:.2f}, R: {R:.2f}, D: {D:.2f}")
    
    # Final state output
    result = {
        "time": round(current_time, 2),
        "susceptible": round(S, 2),
        "exposed": round(E, 2),
        "infective": round(I, 2),
        "recovered": round(R, 2),
        "deceased": round(D, 2)
    }
    
    # Verify population conservation
    total_final = result["susceptible"] + result["exposed"] + result["infective"] + result["recovered"] + result["deceased"]
    if abs(total_final - args.total_population) > 1e-5:
        logging.warning(f"Population conservation check: expected {args.total_population}, got {total_final:.5f}")
    
    # Output final state as JSONL
    print(json.dumps(result))

if __name__ == "__main__":
    main()
</python_code>