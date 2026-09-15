import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
from .StrategicAirlift_D0 import StrategicAirlift_D0

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run StrategicAirlift_D0 simulation")
    
    # Define arguments based on Model Init Args and Scenario Defaults
    parser.add_argument("--duration", type=float, default=10000.0, help="Total simulation time in time units")
    parser.add_argument("--num_aircraft", type=int, default=2, help="Number of aircraft in the system")
    parser.add_argument("--pallet_interval", type=float, default=25.0, help="Time interval between pallet generations")
    parser.add_argument("--pallet_expiration_time", type=float, default=150.0, help="Time window for pallet expiration")
    parser.add_argument("--flight_time", type=float, default=30.0, help="Flight duration for aircraft transport")
    parser.add_argument("--unload_time", type=float, default=2.0, help="Time required for unloading cargo")
    parser.add_argument("--return_time", type=float, default=30.0, help="Return flight duration")
    parser.add_argument("--maintenance_time", type=float, default=10.0, help="Duration of maintenance phase")
    
    args = parser.parse_args()
    ### END

    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock)
    
    model = StrategicAirlift_D0(
        name="StrategicAirlift_D0",
        parent=None,
        duration=args.duration,
        num_aircraft=args.num_aircraft,
        pallet_interval=args.pallet_interval,
        pallet_expiration_time=args.pallet_expiration_time,
        flight_time=args.flight_time,
        unload_time=args.unload_time,
        return_time=args.return_time,
        maintenance_time=args.maintenance_time
    )
    
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    # Advance simulation time. Adding a tiny epsilon ensures events exactly at the boundary are processed.
    sim.simulate_time(args.duration + 1e-9)
    sim.exit()
    ### END