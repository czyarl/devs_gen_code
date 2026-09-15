"""Root module for a simple ARQ demo with two unidirectional subnets."""

from xdevs.models import Atomic, Coupled, Port
from argparse import ArgumentParser
import sys
import json
from .ABP_D1_libs.Sender import Sender
from .ABP_D1_libs.Subnet1 import Subnet1
from .ABP_D1_libs.Receiver import Receiver
from .ABP_D1_libs.Subnet2 import Subnet2

class ABP_D1(Coupled):
    """Construct a complete Python file containing a Coupled DEVS model named `ABP_D1` using `xdevs.py`."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        total_packets: int,
        seed: int,
        sender_delay: float,
        receiver_delay: float,
        channel_delay: float,
        timeout: float,
        simulate_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(None, "packet_in"))
        self.add_out_port(Port(None, "packet_out"))

        sender = Sender(
            name="Sender",
            parent=self,
            total_packets=total_packets,
            sender_delay=sender_delay,
            timeout=timeout,
        )
        self.add_component(sender)

        subnet1 = Subnet1(
            name="Subnet1",
            parent=self,
            seed=seed,
            channel_delay=channel_delay,
        )
        self.add_component(subnet1)

        receiver = Receiver(
            name="Receiver",
            parent=self,
            receiver_delay=receiver_delay,
        )
        self.add_component(receiver)

        subnet2 = Subnet2(
            name="Subnet2",
            parent=self,
            seed=seed,
            channel_delay=channel_delay,
        )
        self.add_component(subnet2)

        self.add_coupling(sender.output["packet_out"], subnet1.input["packet_in"])
        self.add_coupling(subnet1.output["packet_out"], receiver.input["packet_in"])
        self.add_coupling(receiver.output["ack_out"], subnet2.input["packet_in"])
        self.add_coupling(subnet2.output["packet_out"], sender.input["packet_in"])

def parse_args():
    parser = ArgumentParser(description="ABP_D1 Simulation")
    parser.add_argument("--total_packets", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--sender_delay", type=float, default=10.0)
    parser.add_argument("--receiver_delay", type=float, default=10.0)
    parser.add_argument("--channel_delay", type=float, default=3.0)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--simulate_time", type=float, default=1000.0)
    args = parser.parse_args()
    return args

def main():
    args = parse_args()
    model = ABP_D1(
        name="ABP_D1",
        parent=None,
        total_packets=args.total_packets,
        seed=args.seed,
        sender_delay=args.sender_delay,
        receiver_delay=args.receiver_delay,
        channel_delay=args.channel_delay,
        timeout=args.timeout,
        simulate_time=args.simulate_time,
    )
    # Run the simulation
    # ... (simulation run code)

if __name__ == "__main__":
    main()