import argparse
import sys
import json
import logging
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
from .OTrain import OTrain

def parse_time_format(time_str):
    """Parse time string in HH:MM:SS:mmm format to total seconds."""
    h, m, s, ms = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s + ms / 1000.0

def main():
    parser = argparse.ArgumentParser(description="Run OTrain simulation")
    
    # Define arguments based on OTrain model specification
    parser.add_argument("--simulate_time", type=str, default="00:01:00:000", help="Simulation duration in 'HH:MM:SS:mmm' format")
    
    args = parser.parse_args()
    
    # Parse simulate_time
    simulate_time = parse_time_format(args.simulate_time)
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    # Define route sequence according to scenario
    route_sequence = [
        (1, 0), (2, 0), (3, 0), (4, 0), (5, 1), 
        (4, 1), (3, 1), (2, 1), (1, 0)
    ]
    
    model = OTrain( # instance the model
        name="OTrain", 
        parent=None,
        simulate_time=args.simulate_time,
        initial_time=0.0,
        travel_interval=225.0,
        route_sequence=route_sequence,
        initial_passenger_time=0.5,
        mean_interval_minutes=5.0,
        std_interval_minutes=5.0,
        min_interval_minutes=1.0,
        max_interval_minutes=9.0,
        boarding_delay=0.025,
        alighting_delay=0.025
    )
    
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    # Run simulation for the specified duration
    sim.simulate_time(simulate_time)
    sim.exit()
    ### END

if __name__ == "__main__":
    main()