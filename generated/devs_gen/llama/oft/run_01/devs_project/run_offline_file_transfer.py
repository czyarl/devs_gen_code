import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
from .Offline_File_Transfer import Offline_File_Transfer

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Offline_File_Transfer simulation")
    
    parser.add_argument("--simulation_time", type=float, default=10_000_000.0, help="Simulation duration in milliseconds")
    args = parser.parse_args()
    
    simulate_time = args.simulation_time
    
    clock = SimulationClock()
    set_global_clock(clock)
    
    model = Offline_File_Transfer(
        name="Offline_File_Transfer",
        parent=None,
        simulation_time=simulate_time
    )
    sim = Coordinator(model, clock)
    
    sim.initialize()
    sim.simulate_time(simulate_time)
    sim.exit()