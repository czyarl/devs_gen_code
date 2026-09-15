import argparse
import sys
import time
import random
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

# Relative import for the model class as required
from .OTrain import OTrain

def parse_duration(duration_str):
    """
    Parses a duration string in HH:MM:SS:mmm format into float seconds.
    """
    parts = duration_str.split(':')
    if len(parts) != 4:
        raise ValueError(f"Invalid duration format: {duration_str}. Expected HH:MM:SS:mmm")
    
    h, m, s, ms = map(int, parts)
    return h * 3600 + m * 60 + s + ms / 1000.0

if __name__ == "__main__":
    # 1. Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run OTrain simulation")

    # Argument for simulation duration
    parser.add_argument("--simulate_time", type=str, default="00:01:00:000",
                        help="Simulation duration in HH:MM:SS:mmm format")

    # Arguments for OTrain model initialization parameters
    # Defaults are derived from the Simulation Scenario
    parser.add_argument("--travel_interval", type=float, default=225.0,
                        help="Seconds between consecutive stations")
    parser.add_argument("--boarding_delay", type=float, default=0.025,
                        help="Seconds per passenger boarding")
    parser.add_argument("--alighting_delay", type=float, default=0.025,
                        help="Seconds per passenger alighting")
    parser.add_argument("--passenger_gen_mean", type=float, default=5.0,
                        help="Mean time in minutes for passenger generation")
    parser.add_argument("--passenger_gen_std", type=float, default=5.0,
                        help="Std dev time in minutes for passenger generation")

    args = parser.parse_args()

    # Parse the simulation time string to float seconds
    try:
        simulate_time = parse_duration(args.simulate_time)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Define static configuration structures based on the Scenario
    # Station Configuration
    station_configs = [
        {'id': 1, 'name': 'Bayview'},
        {'id': 2, 'name': 'Carling'},
        {'id': 3, 'name': 'Carleton'},
        {'id': 4, 'name': 'Confed'},
        {'id': 5, 'name': 'Greenboro'}
    ]

    # Route Sequence: List of (Station ID, Direction)
    # Direction: 0=Southbound, 1=Northbound
    route_sequence = [
        (1, 0), (2, 0), (3, 0), (4, 0), (5, 1),
        (4, 1), (3, 1), (2, 1), (1, 0)
    ]

    # 2. Initialization
    # Set random seed using system time as required
    random.seed(time.time_ns())

    # Create the global clock and register it
    clock = SimulationClock()
    set_global_clock(clock)

    # Instantiate the OTrain model
    model = OTrain(
        name="OTrain",
        parent=None,
        station_configs=station_configs,
        route_sequence=route_sequence,
        travel_interval=args.travel_interval,
        boarding_delay=args.boarding_delay,
        alighting_delay=args.alighting_delay,
        passenger_gen_mean=args.passenger_gen_mean,
        passenger_gen_std=args.passenger_gen_std
    )

    # Create the Coordinator
    sim = Coordinator(model, clock)

    # 3. Simulation Execution
    sim.initialize()
    
    # Run simulation. 
    # Adding a tiny epsilon to ensure events exactly at the boundary are processed 
    # if the simulator logic stops strictly before the time.
    sim.simulate_time(simulate_time + 1e-9)
    
    sim.exit()