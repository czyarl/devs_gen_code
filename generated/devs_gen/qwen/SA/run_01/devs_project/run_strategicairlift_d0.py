import argparse
import sys
import json
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock, get_current_time

# Import the target model using relative path
from .StrategicAirlift_D0 import StrategicAirlift_D0

def main():
    parser = argparse.ArgumentParser(description="Run StrategicAirlift_D0 simulation")

    # Define arguments matching the model's initialization parameters
    parser.add_argument("--duration", type=float, default=10000.0, help="Total simulation time in time units")
    parser.add_argument("--num_aircraft", type=int, default=2, help="Number of aircraft in the system")
    parser.add_argument("--pallet_interval", type=float, default=25.0, help="Time interval between pallet generations in time units")
    parser.add_argument("--pallet_expiration_time", type=float, default=150.0, help="Time window for pallet expiration (relative to generation)")
    parser.add_argument("--flight_time", type=float, default=30.0, help="Flight duration for aircraft transport in time units")
    parser.add_argument("--unload_time", type=float, default=2.0, help="Time required for unloading cargo at destination")
    parser.add_argument("--return_time", type=float, default=30.0, help="Return flight duration for aircraft")
    parser.add_argument("--maintenance_time", type=float, default=10.0, help="Duration of maintenance phase for aircraft")

    args = parser.parse_args()

    # Assign to local variables for clarity
    duration = args.duration
    num_aircraft = args.num_aircraft
    pallet_interval = args.pallet_interval
    pallet_expiration_time = args.pallet_expiration_time
    flight_time = args.flight_time
    unload_time = args.unload_time
    return_time = args.return_time
    maintenance_time = args.maintenance_time

    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock

    model = StrategicAirlift_D0( # instance the model
        name="StrategicAirlift_D0",
        parent=None,
        duration=duration,
        num_aircraft=num_aircraft,
        pallet_interval=pallet_interval,
        pallet_expiration_time=pallet_expiration_time,
        flight_time=flight_time,
        unload_time=unload_time,
        return_time=return_time,
        maintenance_time=maintenance_time
    )
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    # Run simulation for the specified duration
    # The scenario indicates simulation should stop at the duration time
    # but also mentions that work continues after generation stops.
    # Since the model handles all internal logic, we just simulate until the duration
    sim.simulate_time(duration)
    sim.exit()
    ### END

if __name__ == "__main__":
    main()