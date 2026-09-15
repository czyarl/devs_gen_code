### BEGIN: General Import
import argparse
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
    parser.add_argument("--total_packets", type=int, default=10, help="Total packets to send")
    parser.add_argument("--seed", type=int, default=42, help="Seed for noise generator")
    parser.add_argument("--timeout", type=float, default=20, help="Sender timeout duration")
    parser.add_argument("--sender_delay", type=float, default=10, help="Sender preparation delay")
    parser.add_argument("--receiver_delay", type=float, default=10, help="Receiver processing delay")
    parser.add_argument("--channel_delay", type=float, default=3, help="Subnet transmission delay")
    parser.add_argument("--simulate_time", type=float, default=1000, help="Simulation duration")
    
    args = parser.parse_args()
    
    # Assign to local variables for clarity (optional, can use args.x directly)
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
        channel_delay=channel_delay,
        simulate_time=simulate_time
    )
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    sim.simulate_time(simulate_time)
    sim.exit()
    ### END