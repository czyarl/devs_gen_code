import argparse
import sys
import json
import logging
import collections
import random
import simpy

# Configure logging to output to stderr as requested
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

def run_simulation(args):
    """
    Runs the SEIRD simulation using SimPy for time management.
    """
    # Extract parameters
    N = args.total_population
    I0 = args.initial_infective
    beta = args.transmission_rate
    incubation_period = args.incubation_period
    infectivity_period = args.infectivity_period
    mortality_rate = args.mortality
    dt = args.dt
    sim_time = args.simulation_time

    # Initial State
    # S = N - I_0, E = 0, I = I_0, R = 0, D = 0
    S = float(N - I0)
    E = 0.0
    I = float(I0)
    R = 0.0
    D = 0.0

    # State container to allow modification inside the SimPy process
    state = {
        "S": S, "E": E, "I": I, "R": R, "D": D
    }

    # Setup SimPy Environment
    env = simpy.Environment()

    def seird_process(env, state):
        """
        Generator function representing the SEIRD model process.
        Updates state at fixed time intervals (dt).
        """
        while True:
            current_time = env.now
            
            # Stop if we have reached or passed the simulation time
            if current_time >= sim_time:
                break

            # Retrieve current state values
            S_old = state["S"]
            E_old = state["E"]
            I_old = state["I"]
            R_old = state["R"]
            D_old = state["D"]

            # 1. Calculate new_exposed (S -> E)
            # Formula: (beta * S * I / N) * dt
            # Constraint: new_exposed <= S_old
            if N > 0:
                new_exposed = (beta * S_old * I_old / N) * dt
            else:
                new_exposed = 0.0
            new_exposed = min(new_exposed, S_old)

            # 2. Calculate new_infective (E -> I)
            # Formula: (E / incubation_period) * dt
            # Constraint: new_infective <= E_old
            new_infective = (E_old / incubation_period) * dt
            new_infective = min(new_infective, E_old)

            # 3. Calculate new_deceased (I -> D)
            # Formula: (I / infectivity_period) * (mortality/100) * dt
            new_deceased = (I_old / infectivity_period) * (mortality_rate / 100.0) * dt

            # 4. Calculate new_recovered (I -> R)
            # Formula: (I / infectivity_period) * (1 - mortality/100) * dt
            new_recovered = (I_old / infectivity_period) * (1.0 - mortality_rate / 100.0) * dt

            # 5. Update Compartments
            # S_new = S_old - new_exposed
            S_new = S_old - new_exposed
            
            # E_new = E_old + new_exposed - new_infective
            E_new = E_old + new_exposed - new_infective
            
            # I_new = I_old + new_infective - new_deceased - new_recovered
            I_new = I_old + new_infective - new_deceased - new_recovered
            
            # R_new = R_old + new_recovered
            R_new = R_old + new_recovered
            
            # D_new = D_old + new_deceased
            D_new = D_old + new_deceased

            # Update state dictionary
            state["S"] = S_new
            state["E"] = E_new
            state["I"] = I_new
            state["R"] = R_new
            state["D"] = D_new

            # Debug logging for the step
            logger.debug(f"Time: {current_time:.2f} | S: {S_new:.2f}, E: {E_new:.2f}, I: {I_new:.2f}, R: {R_new:.2f}, D: {D_new:.2f}")

            # Advance time by dt
            yield env.timeout(dt)

    # Add the process to the environment
    env.process(seird_process(env, state))

    # Run the simulation
    env.run(until=sim_time)

    # Prepare the final output object
    output = {
        "time": float(sim_time),
        "susceptible": round(state["S"], 2),
        "exposed": round(state["E"], 2),
        "infective": round(state["I"], 2),
        "recovered": round(state["R"], 2),
        "deceased": round(state["D"], 2)
    }

    return output

def main():
    # Argument Parsing
    parser = argparse.ArgumentParser(description="SEIRD Epidemic Compartmental Model Simulation")
    
    parser.add_argument("--test_name", type=str, required=True, help="Name of the test case being run")
    parser.add_argument("--mortality", type=float, default=10.0, help="Mortality rate as percentage (0-100)")
    parser.add_argument("--infectivity_period", type=float, default=14.0, help="Average days a person stays infectious")
    parser.add_argument("--dt", type=float, default=0.1, help="Time step for numerical integration in days")
    parser.add_argument("--incubation_period", type=float, default=5.0, help="Average days from exposure to becoming infectious")
    parser.add_argument("--total_population", type=int, default=1000, help="Total population size (N)")
    parser.add_argument("--initial_infective", type=int, default=10, help="Initial number of infected individuals (I_0)")
    parser.add_argument("--transmission_rate", type=float, default=2.5, help="Transmission rate (beta) per day")
    parser.add_argument("--simulation_time", type=float, default=10.0, help="Total simulation time in days")

    args = parser.parse_args()

    # Log start
    logger.info(f"Starting Simulation: {args.test_name}")
    logger.info(f"Configuration: N={args.total_population}, I0={args.initial_infective}, beta={args.transmission_rate}, Mortality={args.mortality}%")

    try:
        # Execute simulation
        result = run_simulation(args)
        
        # Output Final State to stdout as JSONL
        print(json.dumps(result))
        
        logger.info("Simulation finished successfully.")
    except Exception as e:
        logger.error(f"An error occurred during simulation: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()