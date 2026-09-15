import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
from .ABP_D1 import ABP_D1

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run ABP_D1 simulation")

    # Define arguments with defaults suitable for the scenario
    parser.add_argument("--total_packets", type=int, default=5, help="Number of packets to send")
    parser.add_argument("--seed", type=int, default=42, help="Noise generator seed for both subnets")
    parser.add_argument("--timeout", type=float, default=20.0, help="Sender's timeout duration in ms")
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

    model = ABP_D1( # instance the model
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
    # Run simulation up to the specified time
    sim.simulate_time(simulate_time)
    sim.exit()
    ### END