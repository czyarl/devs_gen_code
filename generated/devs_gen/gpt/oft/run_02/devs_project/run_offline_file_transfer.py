import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

# The evaluator launches this runner with: python -m package.run
# The leading dot keeps the import within the generated package.
from .Offline_File_Transfer import Offline_File_Transfer


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Offline_File_Transfer simulation")

    # Runner-only stop horizon (ms of simulation time)
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=10_000_000.0,
        help="Simulation duration in milliseconds (simulation time). Default: 10_000_000.0",
    )

    # Offline_File_Transfer model init args (exactly as specified)
    parser.add_argument(
        "--subnet_delay_ms",
        type=float,
        default=3000.0,
        help="Fixed reliable FIFO delay (ms) for each subnet channel A1, A2, B1, B2.",
    )
    parser.add_argument(
        "--sender_preparation_ms",
        type=float,
        default=10000.0,
        help="Sender preparation delay before each (re)send (ms).",
    )
    parser.add_argument(
        "--sender_timeout_ms",
        type=float,
        default=20000.0,
        help="Sender retransmission timeout while waiting for ACK (ms).",
    )
    parser.add_argument(
        "--server_receiver_processing_ms",
        type=float,
        default=3000.0,
        help="ServerReceiver ingress processing delay before ACK/queue decision (ms).",
    )
    parser.add_argument(
        "--receiver_processing_ms",
        type=float,
        default=10000.0,
        help="Receiver processing delay before sending ACK (ms).",
    )

    args = parser.parse_args()

    simulate_time = args.simulation_time

    clock = SimulationClock()
    set_global_clock(clock)

    model = Offline_File_Transfer(
        name="Offline_File_Transfer",
        parent=None,
        subnet_delay_ms=args.subnet_delay_ms,
        sender_preparation_ms=args.sender_preparation_ms,
        sender_timeout_ms=args.sender_timeout_ms,
        server_receiver_processing_ms=args.server_receiver_processing_ms,
        receiver_processing_ms=args.receiver_processing_ms,
    )
    sim = Coordinator(model, clock)

    sim.initialize()
    # Treat simulation_time as an inclusive observation horizon.
    sim.simulate_time(simulate_time + 1e-9)
    sim.exit()


if __name__ == "__main__":
    main()