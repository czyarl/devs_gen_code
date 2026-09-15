import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

# The evaluator launches this runner as a package module (e.g., python -m ...),
# so the import must be relative.
from .House_Heating_D1 import House_Heating_D1


if __name__ == "__main__":
    # 2. Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run House_Heating_D1 simulation")

    # Model init args (exactly as declared by House_Heating_D1)
    parser.add_argument("--name", type=str, default="House_Heating_D1", help="Model instance name")
    parser.add_argument("--default_outdoor_temp_c", type=float, default=25.0,
                        help="Default outdoor temperature when no schedule exists at/before time")
    parser.add_argument("--target_temp_c", type=float, default=24.9, help="Controller target temperature (C)")
    parser.add_argument("--heat_loss_rate", type=float, default=0.10, help="Per-step heat loss fraction")
    parser.add_argument("--heater_gain_c", type=float, default=0.5, help="Heater gain (C) when heater is on")
    parser.add_argument("--initial_room_temp_c", type=float, default=25.0, help="Initial room temperature (C)")
    parser.add_argument("--initial_control_signal", type=int, default=0, help="Initial control signal (0/1)")
    parser.add_argument("--simulate_time", type=float, default=60.0,
                        help="Total simulation duration in seconds (observations expected for 1..int(simulate_time))")

    args = parser.parse_args()

    # Runner-local horizon (also passed to the model because it is a declared init arg)
    simulate_time = float(args.simulate_time)

    # 3. Initialization (strict order)
    clock = SimulationClock()
    set_global_clock(clock)

    model = House_Heating_D1(
        name=args.name,
        parent=None,
        default_outdoor_temp_c=float(args.default_outdoor_temp_c),
        target_temp_c=float(args.target_temp_c),
        heat_loss_rate=float(args.heat_loss_rate),
        heater_gain_c=float(args.heater_gain_c),
        initial_room_temp_c=float(args.initial_room_temp_c),
        initial_control_signal=int(args.initial_control_signal),
        simulate_time=simulate_time,
    )

    sim = Coordinator(model, clock)

    # 4. Simulation Execution
    sim.initialize()
    # Inclusive integer-second observation horizon: ensure events exactly at the bound are included.
    sim.simulate_time(simulate_time + 1e-9)
    sim.exit()