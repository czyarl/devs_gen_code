"""Coupled root model encapsulating the Alternating Bit Protocol (ABP) system."""

from xdevs.models import Atomic, Coupled, Port

from .ABP_D1_libs.Sender import Sender
from .ABP_D1_libs.Receiver import Receiver
from .ABP_D1_libs.Subnet1 import Subnet1
from .ABP_D1_libs.Subnet2 import Subnet2


class ABP_D1(Coupled):
    """Coupled root model encapsulating the Alternating Bit Protocol (ABP) system."""

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

        # Instantiate Atomic Components
        sender = Sender(
            name="Sender",
            parent=self,
            total_packets=total_packets,
            timeout=timeout,
            sender_delay=sender_delay,
        )

        receiver = Receiver(
            name="Receiver",
            parent=self,
            receiver_delay=receiver_delay,
        )

        subnet1 = Subnet1(
            name="Subnet1",
            parent=self,
            seed=seed,
            channel_delay=channel_delay,
        )

        subnet2 = Subnet2(
            name="Subnet2",
            parent=self,
            seed=seed,
            channel_delay=channel_delay,
        )

        # Register components
        self.add_component(sender)
        self.add_component(receiver)
        self.add_component(subnet1)
        self.add_component(subnet2)

        # Define Internal Couplings
        # Connect Sender.packet_out to Subnet1.packet_in
        self.add_coupling(
            sender.output["packet_out"],
            subnet1.input["packet_in"],
        )

        # Connect Subnet1.packet_out to Receiver.packet_in
        self.add_coupling(
            subnet1.output["packet_out"],
            receiver.input["packet_in"],
        )

        # Connect Receiver.ack_out to Subnet2.ack_in
        self.add_coupling(
            receiver.output["ack_out"],
            subnet2.input["ack_in"],
        )

        # Connect Subnet2.ack_out to Sender.ack_in
        self.add_coupling(
            subnet2.output["ack_out"],
            sender.input["ack_in"],
        )