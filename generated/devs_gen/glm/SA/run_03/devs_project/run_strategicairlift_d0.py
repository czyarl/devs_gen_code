### BEGIN: General Import
import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
### END

# The evaluator launches this runner with ``python -m package.runner``.
# The leading dot keeps the model import inside that generated package.
### BEGIN: Model import, must be relative
from .StrategicAirlift_D0 import StrategicAirlift_D0
### END

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run StrategicAirlift_D0 simulation")
    
    # Define arguments based on Model Specification and Simulation Scenario
    parser.add_argument("--duration", type=float, default=10000.0, help="Total simulation time")
    parser.add_argument("--num_aircraft", type=int, default=2, help="Number of aircraft instances")
    parser.add_argument("--pallet_interval", type=float, default=25.0, help="Time between pallet generations")
    parser.add_argument("--pallet_expiration_time", type=float, default=150.0, help="Time window for pallet expiration")
    parser.add_argument("--flight_time", type=float, default=30.0, help="Duration of flight to destination")
    parser.add_argument("--unload_time", type=float, default=2.0, help="Duration of unloading at destination")
    parser.add_argument("--return_time", type=float, default=30.0, help="Duration of return flight")
    parser.add_argument("--maintenance_time", type=float, default=10.0, help="Duration of maintenance")
    
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
    
    model = StrategicAirlift_D0(
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
    # The scenario specifies simulation continues until total_duration is reached.
    # Adding a small epsilon ensures events exactly at the boundary are processed.
    sim.simulate_time(duration + 1e-9)
    sim.exit()
    ### END