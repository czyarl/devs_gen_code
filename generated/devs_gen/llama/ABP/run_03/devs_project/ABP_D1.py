"""ABP_D1: Top-level coupled model."""

from xdevs.models import Atomic, Coupled, Port
from argparse import ArgumentParser
import sys
import json
from .ABP_D1_libs.Sender import Sender
from .ABP_D1_libs.Subnet1 import Subnet1
from .ABP_D1_libs.Receiver import Receiver
from .ABP_D1_libs.Subnet2 import Subnet2


class ABP_D1(Coupled):
    """Top-level coupled model for ABP_D1."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        total_packets: int,
        seed: int,
        timeout: float,
        sender_delay: float,
        receiver_delay: float,
        channel_delay: float,
        simulate_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "packet_in"))
        self.add_out_port(Port(dict, "packet_out"))

        sender = Sender(
            name="Sender",
            parent=self,
            total_packets=total_packets,
            timeout=timeout,
            sender_delay=sender_delay,
        )
        subnet1 = Subnet1(
            name="Subnet1",
            parent=self,
            seed=seed,
            channel_delay=channel_delay,
        )
        receiver = Receiver(
            name="Receiver",
            parent=self,
            receiver_delay=receiver_delay,
        )
        subnet2 = Subnet2(
            name="Subnet2",
            parent=self,
            seed=seed,
            channel_delay=channel_delay,
        )

        self.add_component(sender)
        self.add_component(subnet1)
        self.add_component(receiver)
        self.add_component(subnet2)

        self.add_coupling(
            sender.output["packet_sent"],
            subnet1.input["packet_in"],
        )
        self.add_coupling(
            subnet1.output["packet_out"],
            receiver.input["packet_in"],
        )
        self.add_coupling(
            receiver.output["ack_sent"],
            subnet2.input["packet_in"],
        )
        self.add_coupling(
            subnet2.output["packet_out"],
            sender.input["packet_in"],
        )


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--total_packets", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--sender_delay", type=float, default=10)
    parser.add_argument("--receiver_delay", type=float, default=10)
    parser.add_argument("--channel_delay", type=float, default=3)
    parser.add_argument("--simulate_time", type=float, default=1000)
    args = parser.parse_args()

    coupled_model = ABP_D1(
        name="ABP_D1",
        parent=None,
        total_packets=args.total_packets,
        seed=args.seed,
        timeout=args.timeout,
        sender_delay=args.sender_delay,
        receiver_delay=args.receiver_delay,
        channel_delay=args.channel_delay,
        simulate_time=args.simulate_time,
    )
    coupled_model.simulate(simulate_time=args.simulate_time)