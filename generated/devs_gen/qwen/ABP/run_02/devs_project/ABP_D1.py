"""Coupled DEVS model ABP_D1 orchestrating Sender, Receiver, and two Subnets."""

from xdevs.models import Atomic, Coupled, Port
from .ABP_D1_libs.Sender import Sender
from .ABP_D1_libs.Receiver import Receiver
from .ABP_D1_libs.Subnet1 import Subnet1
from .ABP_D1_libs.Subnet2 import Subnet2


class ABP_D1(Coupled):
    """Orchestrates the communication system involving Sender, Receiver, and two Subnets."""

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
    ):
        super().__init__(name)
        self.parent = parent

        # Instantiate components
        sender = Sender(
            name="sender",
            parent=self,
            total_packets=total_packets,
            sender_delay=sender_delay,
            timeout=timeout,
        )
        receiver = Receiver(
            name="receiver",
            parent=self,
            receiver_delay=receiver_delay,
        )
        subnet1 = Subnet1(
            name="subnet1",
            parent=self,
            channel_delay=channel_delay,
            noise_seed=seed,
        )
        subnet2 = Subnet2(
            name="subnet2",
            parent=self,
            channel_delay=channel_delay,
            noise_seed=seed,
        )

        # Register components
        self.add_component(sender)
        self.add_component(receiver)
        self.add_component(subnet1)
        self.add_component(subnet2)

        # Define couplings as per the locked contract
        self.add_coupling(
            sender.output["packet_sent"],
            subnet1.input["packet_in"],
        )
        self.add_coupling(
            subnet1.output["packet_out"],
            receiver.input["packet_in"],
        )
        self.add_coupling(
            receiver.output["ack_out"],
            subnet2.input["ack_in"],
        )
        self.add_coupling(
            subnet2.output["ack_out"],
            sender.input["ack_in"],
        )
        self.add_coupling(
            sender.output["delay_start"],
            receiver.input["delay_start"],
        )
        self.add_coupling(
            subnet1.output["packet_get"],
            sender.input["ack_received"],
        )
        self.add_coupling(
            subnet2.output["packet_get"],
            sender.input["ack_received"],
        )