import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

# The evaluator launches this runner with ``python -m package.runner``.
# The leading dot keeps the model import inside that generated package.
from .ABP_D1 import ABP_D1

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run ABP_D1 simulation")
    
    # Define arguments based on the Simulation Scenario and Model Specification
    # Defaults are derived from the scenario requirements
    parser.add_argument("--total_packets", type=int, default=10, help="Total number of packets to send")
    parser.add_argument("--seed", type=int, default=42, help="Initialization seed for noise generator")
    parser.add_argument("--timeout", type=int, default=20, help="Sender timeout duration in ms")
    parser.add_argument("--sender_delay", type=int, default=10, help="Sender preparation delay in ms")
    parser.add_argument("--receiver_delay", type=int, default=10, help="Receiver processing delay in ms")
    parser.add_argument("--channel_delay", type=int, default=3, help="Subnet transmission delay in ms")
    parser.add_argument("--simulate_time", type=int, default=1000, help="Total simulation time to run in ms")
    
    args = parser.parse_args()
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    # Instantiate the model with configuration parameters
    # Note: Casting to float where the model expects float, though argparse types are int as per scenario
    model = ABP_D1(
        name="ABP_D1", 
        parent=None,
        total_packets=args.total_packets,
        seed=args.seed,
        timeout=float(args.timeout),
        sender_delay=float(args.sender_delay),
        receiver_delay=float(args.receiver_delay),
        channel_delay=float(args.channel_delay)
    )
    
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    
    # The scenario defines a fixed observation horizon via --simulate_time.
    # We add a tiny epsilon to ensure events exactly at the boundary are included.
    sim.simulate_time(float(args.simulate_time) + 1e-9)
    
    sim.exit()
    ### END