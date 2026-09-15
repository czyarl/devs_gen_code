import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

# The evaluator launches this runner with: python -m package.runner
# The leading dot keeps the model import inside the generated package.
from .ABP_D1 import ABP_D1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ABP_D1 simulation (xDEVS)")

    # Model init args (must match ABP_D1.__init__ signature)
    parser.add_argument(
        "--total_packets",
        type=int,
        default=10,
        help="Total number of data packets Sender must deliver reliably (seq_num 1..total_packets).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Initial noise-state x for BOTH subnet instances (both start from this value).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Sender stop-and-wait timeout duration in ms.",
    )
    parser.add_argument(
        "--sender_delay",
        type=float,
        default=10.0,
        help="Sender preparation delay in ms before every send/retransmission.",
    )
    parser.add_argument(
        "--receiver_delay",
        type=float,
        default=10.0,
        help="Receiver processing delay in ms per delivered data packet.",
    )
    parser.add_argument(
        "--channel_delay",
        type=float,
        default=3.0,
        help="Fixed latency in ms applied by each subnet when a packet is passed (not dropped).",
    )

    # Runner-only stop horizon
    parser.add_argument(
        "--simulate_time",
        type=float,
        default=1000.0,
        help="Total simulation time to run in ms.",
    )

    args = parser.parse_args()

    total_packets = args.total_packets
    seed = args.seed
    timeout = args.timeout
    sender_delay = args.sender_delay
    receiver_delay = args.receiver_delay
    channel_delay = args.channel_delay
    simulate_time = args.simulate_time

    clock = SimulationClock()
    set_global_clock(clock)

    model = ABP_D1(
        name="ABP_D1",
        parent=None,
        total_packets=total_packets,
        seed=seed,
        timeout=timeout,
        sender_delay=sender_delay,
        receiver_delay=receiver_delay,
        channel_delay=channel_delay,
    )

    sim = Coordinator(model, clock)

    sim.initialize()
    # Treat simulate_time as an inclusive observation horizon.
    sim.simulate_time(simulate_time + 1e-9)
    sim.exit()


if __name__ == "__main__":
    main()