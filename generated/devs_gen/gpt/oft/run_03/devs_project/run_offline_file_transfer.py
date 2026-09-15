import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

# The evaluator launches this runner with ``python -m package.run`` (or similar).
# The leading dot keeps the model import inside that generated package.
from .Offline_File_Transfer import Offline_File_Transfer


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Offline_File_Transfer simulation")

    # Runner-only stop horizon (milliseconds of simulation time)
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=10_000_000.0,
        help="Simulation duration (stop horizon) in milliseconds of simulation time.",
    )

    # Model init args (must match Offline_File_Transfer.__init__ signature)
    parser.add_argument(
        "--link_delay_ms",
        type=float,
        default=3000.0,
        help="Fixed one-way delay for each reliable FIFO subnet link (ms).",
    )
    parser.add_argument(
        "--sender_preparation_ms",
        type=float,
        default=10000.0,
        help="Sender preparation delay before sending (ms).",
    )
    parser.add_argument(
        "--sender_timeout_ms",
        type=float,
        default=20000.0,
        help="Sender ACK timeout before retransmission (ms).",
    )
    parser.add_argument(
        "--server_receiver_processing_ms",
        type=float,
        default=3000.0,
        help="ServerReceiver processing delay per received upload packet (ms).",
    )
    parser.add_argument(
        "--receiver_processing_ms",
        type=float,
        default=10000.0,
        help="Receiver processing delay per received download packet (ms).",
    )

    args = parser.parse_args()

    simulate_time = float(args.simulation_time)

    clock = SimulationClock()
    set_global_clock(clock)

    model = Offline_File_Transfer(
        name="Offline_File_Transfer",
        parent=None,
        link_delay_ms=float(args.link_delay_ms),
        sender_preparation_ms=float(args.sender_preparation_ms),
        sender_timeout_ms=float(args.sender_timeout_ms),
        server_receiver_processing_ms=float(args.server_receiver_processing_ms),
        receiver_processing_ms=float(args.receiver_processing_ms),
    )

    sim = Coordinator(model, clock)

    sim.initialize()
    # Treat simulation_time as an inclusive observation horizon.
    sim.simulate_time(simulate_time + 1e-9)
    sim.exit()


if __name__ == "__main__":
    main()