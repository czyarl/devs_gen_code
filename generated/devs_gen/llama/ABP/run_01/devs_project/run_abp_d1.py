### BEGIN: General Import
import argparse
import json
import logging
import sys
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
### END

### BEGIN: Model import, must be relative
from .ABP_D1 import ABP_D1
### END

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run ABP_D1 simulation")
    
    # Define arguments with defaults suitable for the scenario
    parser.add_argument("--total_packets", type=int, default=10, help="Total number of packets to send")
    parser.add_argument("--seed", type=int, default=42, help="Seed for deterministic noise")
    parser.add_argument("--sender_delay", type=float, default=10, help="Sender preparation delay in ms")
    parser.add_argument("--receiver_delay", type=float, default=10, help="Receiver processing delay in ms")
    parser.add_argument("--channel_delay", type=float, default=3, help="Subnet transmission delay in ms")
    parser.add_argument("--timeout", type=float, default=20, help="Sender timeout duration in ms")
    parser.add_argument("--simulate_time", type=float, default=1000, help="Simulation duration in ms")
    
    args = parser.parse_args()
    
    # Assign to local variables for clarity (optional, can use args.x directly)
    total_packets = args.total_packets
    seed = args.seed
    sender_delay = args.sender_delay
    receiver_delay = args.receiver_delay
    channel_delay = args.channel_delay
    timeout = args.timeout
    simulate_time = args.simulate_time
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    model = ABP_D1( # instance the model
        name="ABP_D1", 
        parent=None,
        total_packets=total_packets,
        seed=seed,
        sender_delay=sender_delay,
        receiver_delay=receiver_delay,
        channel_delay=channel_delay,
        timeout=timeout,
        simulate_time=simulate_time
    )
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    sim.simulate_time(simulate_time)
    sim.exit()
    ### END