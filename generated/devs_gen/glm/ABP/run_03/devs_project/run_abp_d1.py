### BEGIN: General Import
import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
### END

# The evaluator launches this runner with ``python -m package.runner``.
# The leading dot keeps the model import inside that generated package.
### BEGIN: Model import, must be relative
from .ABP_D1 import ABP_D1
### END

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run ABP_D1 simulation")
    
    # Define arguments based on the Simulation Scenario and Model Specification
    # Defaults are derived from the scenario description
    parser.add_argument("--total_packets", type=int, default=1, help="Total number of packets to send")
    parser.add_argument("--seed", type=int, default=42, help="Initialization seed for the noise generator")
    parser.add_argument("--timeout", type=int, default=20, help="Sender's timeout duration in ms")
    parser.add_argument("--sender_delay", type=int, default=10, help="Sender preparation delay in ms")
    parser.add_argument("--receiver_delay", type=int, default=10, help="Receiver processing delay in ms")
    parser.add_argument("--channel_delay", type=int, default=3, help="Subnet transmission delay in ms")
    parser.add_argument("--simulate_time", type=int, default=1000, help="The total simulation time to run in ms")
    
    args = parser.parse_args()
    
    # Assign to local variables for clarity
    total_packets = args.total_packets
    seed = args.seed
    timeout = args.timeout
    sender_delay = args.sender_delay
    receiver_delay = args.receiver_delay
    channel_delay = args.channel_delay
    simulate_time = args.simulate_time
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    # Instantiate the model with arguments matching the specification
    # Note: Casting int arguments to float where the model specification expects float
    model = ABP_D1(
        name="ABP_D1", 
        parent=None,
        total_packets=total_packets,
        seed=seed,
        timeout=float(timeout),
        sender_delay=float(sender_delay),
        receiver_delay=float(receiver_delay),
        channel_delay=float(channel_delay)
    )
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    # Run simulation. Adding a small epsilon to ensure events exactly at the horizon are processed.
    sim.simulate_time(float(simulate_time) + 1e-9)
    sim.exit()
    ### END