import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
from .House_Heating_D1 import House_Heating_D1

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run House_Heating_D1 simulation")
    
    # Define arguments with defaults suitable for the scenario
    parser.add_argument("--simulate_time", type=float, default=10.0, help="Total simulation duration in seconds")
    parser.add_argument("--default_outdoor_temp", type=float, default=25.0, help="Default outdoor temperature")
    parser.add_argument("--initial_room_temp", type=float, default=25.0, help="Initial room temperature")
    parser.add_argument("--target_temp", type=float, default=24.9, help="Target temperature")
    parser.add_argument("--heater_gain", type=float, default=0.5, help="Heater gain")
    parser.add_argument("--loss_rate", type=float, default=0.1, help="Heat loss rate")
    
    args = parser.parse_args()
    
    # Assign to local variables for clarity
    simulate_time = args.simulate_time
    default_outdoor_temp = args.default_outdoor_temp
    initial_room_temp = args.initial_room_temp
    target_temp = args.target_temp
    heater_gain = args.heater_gain
    loss_rate = args.loss_rate
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    model = House_Heating_D1(
        name="House_Heating_D1",
        parent=None,
        simulate_time=simulate_time,
        default_outdoor_temp=default_outdoor_temp,
        initial_room_temp=initial_room_temp,
        target_temp=target_temp,
        heater_gain=heater_gain,
        loss_rate=loss_rate
    )
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    # Advance to the observation horizon. Add a tiny epsilon to ensure
    # the event exactly at the boundary (if any) is processed.
    sim.simulate_time(simulate_time + 1e-9)
    sim.exit()
    ### END