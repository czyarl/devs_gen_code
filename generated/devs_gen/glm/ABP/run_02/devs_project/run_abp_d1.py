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
    
    # Define arguments based on Model Specification and Scenario requirements
    # Model init args: total_packets, seed, timeout, sender_delay, receiver_delay, channel_delay
    # Scenario args: simulate_time (runner only)
    
    parser.add_argument("--total_packets", type=int, default=10, help="Total number of packets to send")
    parser.add_argument("--seed", type=int, default=42, help="Initial noise seed for subnets")
    parser.add_argument("--timeout", type=float, default=20.0, help="Sender timeout duration in ms")
    parser.add_argument("--sender_delay", type=float, default=10.0, help="Sender preparation delay in ms")
    parser.add_argument("--receiver_delay", type=float, default=10.0, help="Receiver processing delay in ms")
    parser.add_argument("--channel_delay", type=float, default=3.0, help="Subnet transmission delay in ms")
    parser.add_argument("--simulate_time", type=float, default=1000.0, help="Simulation duration in ms")
    
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
    
    # Instantiate the model
    # Note: simulate_time is NOT passed to the model as it is not in model_init_args
    model = ABP_D1(
        name="ABP_D1",
        parent=None,
        total_packets=total_packets,
        seed=seed,
        timeout=timeout,
        sender_delay=sender_delay,
        receiver_delay=receiver_delay,
        channel_delay=channel_delay
    )
    
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    # Run to the observation horizon + epsilon to include boundary events
    sim.simulate_time(simulate_time + 1e-9)
    sim.exit()
    ### END