import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
from .Offline_File_Transfer import Offline_File_Transfer

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run Offline_File_Transfer simulation")
    
    # Simulation duration argument
    parser.add_argument("--simulation_time", type=float, default=10000_000.0, help="Simulation duration in milliseconds")
    
    # Model initialization arguments based on specification
    parser.add_argument("--sender_preparation_delay", type=float, default=10000.0, help="Sender preparation delay in ms")
    parser.add_argument("--sender_timeout", type=float, default=20000.0, help="Sender timeout in ms")
    parser.add_argument("--server_receiver_processing_delay", type=float, default=3000.0, help="Server receiver processing delay in ms")
    parser.add_argument("--receiver_processing_delay", type=float, default=10000.0, help="Receiver processing delay in ms")
    parser.add_argument("--subnet_delay", type=float, default=3000.0, help="Subnet delay in ms")
    
    args = parser.parse_args()
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    model = Offline_File_Transfer(
        name="Offline_File_Transfer",
        parent=None,
        sender_preparation_delay=args.sender_preparation_delay,
        sender_timeout=args.sender_timeout,
        server_receiver_processing_delay=args.server_receiver_processing_delay,
        receiver_processing_delay=args.receiver_processing_delay,
        subnet_delay=args.subnet_delay
    )
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    # Advance simulation time. Adding a tiny epsilon to ensure events exactly at the horizon are processed.
    sim.simulate_time(args.simulation_time + 1e-9)
    sim.exit()
    ### END