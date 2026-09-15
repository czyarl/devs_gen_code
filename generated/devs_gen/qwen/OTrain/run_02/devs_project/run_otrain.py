import argparse
import sys
import json
import logging
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
from .OTrain import OTrain

def parse_time_format(time_str):
    """Parse time string in HH:MM:SS:mmm format to seconds."""
    try:
        hours, minutes, seconds, milliseconds = map(int, time_str.split(':'))
        total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
        return total_seconds
    except Exception as e:
        raise ValueError(f"Invalid time format '{time_str}'. Expected HH:MM:SS:mmm") from e

def main():
    parser = argparse.ArgumentParser(description="Run OTrain simulation")
    
    # Define arguments according to the model specification and scenario
    parser.add_argument("--simulate_time", type=str, default="00:01:00:000", 
                        help="Simulation duration in HH:MM:SS:mmm format")
    
    args = parser.parse_args()
    
    # Parse simulate_time
    simulate_time = parse_time_format(args.simulate_time)
    
    # Set random seed using system time
    import random
    import time
    random.seed(time.time_ns())
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    # Define parameters according to the scenario
    initial_station_id = 1
    initial_direction = 0
    travel_interval = 225.0
    route_sequence = [
        (1, 0), (2, 0), (3, 0), (4, 0), (5, 1),
        (4, 1), (3, 1), (2, 1), (1, 0)
    ]
    initial_arrival_time = 0.5
    mean_interval_minutes = 5.0
    std_interval_minutes = 5.0
    interval_min_minutes = 1.0
    interval_max_minutes = 9.0
    
    model = OTrain( # instance the model
        name="OTrain", 
        parent=None,
        simulate_time=args.simulate_time,
        initial_station_id=initial_station_id,
        initial_direction=initial_direction,
        travel_interval=travel_interval,
        route_sequence=route_sequence,
        initial_arrival_time=initial_arrival_time,
        mean_interval_minutes=mean_interval_minutes,
        std_interval_minutes=std_interval_minutes,
        interval_min_minutes=interval_min_minutes,
        interval_max_minutes=interval_max_minutes
    )
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    # Run simulation up to the specified time
    sim.simulate_time(simulate_time)
    sim.exit()
    ### END

if __name__ == "__main__":
    main()