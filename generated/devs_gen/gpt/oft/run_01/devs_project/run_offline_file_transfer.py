import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

# The evaluator launches this runner with ``python -m package.run`` (as a module).
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
        "--sender_preparation_delay_ms",
        type=float,
        default=10_000.0,
        help="Sender preparation delay before each (re)send (ms).",
    )
    parser.add_argument(
        "--sender_ack_timeout_ms",
        type=float,
        default=20_000.0,
        help="Sender timeout waiting for correct ACK before retransmission (ms).",
    )
    parser.add_argument(
        "--server_receiver_processing_delay_ms",
        type=float,
        default=3_000.0,
        help="ServerReceiver processing delay before ACK decision (ms).",
    )
    parser.add_argument(
        "--receiver_processing_delay_ms",
        type=float,
        default=10_000.0,
        help="Receiver processing delay before sending ACK (ms).",
    )
    parser.add_argument(
        "--subnet_delay_ms",
        type=float,
        default=3_000.0,
        help="Fixed delay for each reliable FIFO subnet link (ms).",
    )

    args = parser.parse_args()

    simulate_time_ms = args.simulation_time

    clock = SimulationClock()
    set_global_clock(clock)

    model = Offline_File_Transfer(
        name="Offline_File_Transfer",
        parent=None,
        sender_preparation_delay_ms=args.sender_preparation_delay_ms,
        sender_ack_timeout_ms=args.sender_ack_timeout_ms,
        server_receiver_processing_delay_ms=args.server_receiver_processing_delay_ms,
        receiver_processing_delay_ms=args.receiver_processing_delay_ms,
        subnet_delay_ms=args.subnet_delay_ms,
    )

    sim = Coordinator(model, clock)

    sim.initialize()
    # Treat as inclusive observation horizon; allow events exactly at the boundary.
    sim.simulate_time(simulate_time_ms + 1e-9)
    sim.exit()


if __name__ == "__main__":
    main()