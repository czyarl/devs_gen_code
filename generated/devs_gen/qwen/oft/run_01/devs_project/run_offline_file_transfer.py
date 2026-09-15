import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
from .Offline_File_Transfer import Offline_File_Transfer

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run Offline_File_Transfer simulation")
    
    # Define arguments with defaults suitable for the scenario
    parser.add_argument("--simulation_time", type=float, default=10000000.0, help="Simulation duration in milliseconds")
    parser.add_argument("--preparation_delay", type=float, default=10000.0, help="Fixed preparation delay in milliseconds for packet sending.")
    parser.add_argument("--timeout_duration", type=float, default=20000.0, help="Timeout duration in milliseconds for waiting for ACK.")
    parser.add_argument("--processing_delay", type=float, default=3000.0, help="Processing delay in milliseconds for ServerReceiver and Receiver.")
    parser.add_argument("--link_delay", type=float, default=3000.0, help="Fixed delay in milliseconds for all subnets.")
    
    args = parser.parse_args()
    
    # Assign to local variables for clarity
    simulation_time = args.simulation_time
    preparation_delay = args.preparation_delay
    timeout_duration = args.timeout_duration
    processing_delay = args.processing_delay
    link_delay = args.link_delay
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    model = Offline_File_Transfer( # instance the model
        name="Offline_File_Transfer", 
        parent=None,
        simulation_time=simulation_time,
        preparation_delay=preparation_delay,
        timeout_duration=timeout_duration,
        processing_delay=processing_delay,
        link_delay=link_delay
    )
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    # The scenario specifies a fixed simulation time, so we run to that horizon.
    # xDEVS stops before an event exactly at the requested bound, so advance
    # by a tiny amount when the scenario requires the boundary event.
    sim.simulate_time(simulation_time + 1e-9)
    sim.exit()
    ### END