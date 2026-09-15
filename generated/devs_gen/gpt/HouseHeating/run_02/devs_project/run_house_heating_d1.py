import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

# The evaluator launches this runner with ``python -m package.run`` (as a module).
# The leading dot keeps the model import inside that generated package.
from .House_Heating_D1 import House_Heating_D1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run House_Heating_D1 simulation")

    # Benchmark-required CLI option name
    parser.add_argument(
        "--simulate_time",
        type=float,
        default=60.0,
        help="Total simulation duration in seconds (observations expected for seconds 1..int(simulate_time)).",
    )

    # Model init args (exactly as declared by House_Heating_D1)
    parser.add_argument(
        "--default_outdoor_temp_c",
        type=float,
        default=25.0,
        help="Default scheduled outdoor temperature when no stdin reading timestamp is <= query time.",
    )
    parser.add_argument(
        "--heat_loss_factor",
        type=float,
        default=0.10,
        help="Fraction of (prev_room_temp - effective_outdoor_temp) lost per second.",
    )
    parser.add_argument(
        "--heater_gain_c",
        type=float,
        default=0.5,
        help="Heater adds this many °C in a step when previous control_signal==1.",
    )
    parser.add_argument(
        "--control_threshold_c",
        type=float,
        default=24.9,
        help="Set next control_signal to 1 when new room_temp_c < this threshold, else 0.",
    )
    parser.add_argument(
        "--initial_room_temp_c",
        type=float,
        default=25.0,
        help="Initial room temperature at simulation time 0.",
    )
    parser.add_argument(
        "--initial_control_signal",
        type=int,
        default=0,
        help="Initial control signal at time 0 (0 or 1).",
    )

    args = parser.parse_args()

    simulate_time = float(args.simulate_time)

    clock = SimulationClock()
    set_global_clock(clock)

    model = House_Heating_D1(
        name="House_Heating_D1",
        parent=None,
        simulation_time=simulate_time,
        default_outdoor_temp_c=float(args.default_outdoor_temp_c),
        heat_loss_factor=float(args.heat_loss_factor),
        heater_gain_c=float(args.heater_gain_c),
        control_threshold_c=float(args.control_threshold_c),
        initial_room_temp_c=float(args.initial_room_temp_c),
        initial_control_signal=int(args.initial_control_signal),
    )

    sim = Coordinator(model, clock)

    sim.initialize()
    # Treat duration as an inclusive observation horizon; include boundary events if any.
    sim.simulate_time(simulate_time + 1e-9)
    sim.exit()