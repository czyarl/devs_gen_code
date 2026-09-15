import argparse
import json
import sys
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
from .House_Heating_D1 import House_Heating_D1

def main():
    parser = argparse.ArgumentParser(description="Run House_Heating_D1 simulation")
    
    # Define arguments with defaults suitable for the scenario
    parser.add_argument("--simulate_time", type=float, default=10.0, help="Simulation duration")
    args = parser.parse_args()
    
    simulate_time = args.simulate_time

    clock = SimulationClock()
    set_global_clock(clock) 

    model = House_Heating_D1(
        name="House_Heating_D1", 
        parent=None,
        simulation_time=simulate_time
    )
    sim = Coordinator(model, clock)

    sim.initialize()
    sim.simulate_time(simulate_time)
    sim.exit()

if __name__ == "__main__":
    main()