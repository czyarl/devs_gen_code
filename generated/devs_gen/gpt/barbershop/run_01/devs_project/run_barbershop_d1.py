import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

# The evaluator launches this runner with ``python -m package.run`` (as a module).
# The leading dot keeps the model import inside that generated package.
from .Barbershop_D1 import Barbershop_D1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Barbershop_D1 simulation")

    # Runner stop horizon (scenario-defined CLI argument name)
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=1000000.0,
        help="Total simulation time in seconds.",
    )

    # Model init args (exactly as declared by Barbershop_D1)
    parser.add_argument(
        "--reception_queue_capacity",
        type=int,
        default=8,
        help="Strict maximum number of customers allowed in reception waiting area.",
    )
    parser.add_argument(
        "--reception_checkin_time_s",
        type=float,
        default=5.0,
        help="Reception check-in processing time per customer in seconds.",
    )
    parser.add_argument(
        "--checkhair_consult_time_s",
        type=float,
        default=7.0,
        help="Hair inspection/consultation time per customer in seconds.",
    )
    parser.add_argument(
        "--cuthair_cut_time_s",
        type=float,
        default=20.0,
        help="Hair cutting time per customer in seconds.",
    )

    args = parser.parse_args()

    simulation_time = args.simulation_time

    clock = SimulationClock()
    set_global_clock(clock)

    model = Barbershop_D1(
        name="Barbershop_D1",
        parent=None,
        reception_queue_capacity=args.reception_queue_capacity,
        reception_checkin_time_s=args.reception_checkin_time_s,
        checkhair_consult_time_s=args.checkhair_consult_time_s,
        cuthair_cut_time_s=args.cuthair_cut_time_s,
    )

    sim = Coordinator(model, clock)

    sim.initialize()
    # Treat as an inclusive observation horizon; include events exactly at the boundary.
    sim.simulate_time(simulation_time + 1e-9)
    sim.exit()


if __name__ == "__main__":
    main()