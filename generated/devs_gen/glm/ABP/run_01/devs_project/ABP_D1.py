from xdevs.models import Atomic, Coupled, Port

from .ABP_D1_libs.Sender import Sender
from .ABP_D1_libs.Receiver import Receiver
from .ABP_D1_libs.Subnet1 import Subnet1
from .ABP_D1_libs.Subnet2 import Subnet2


class ABP_D1(Coupled):
    """Coupled model for the Alternating Bit Protocol system."""

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

        # Instantiate children
        sender = Sender(
            name="Sender",
            parent=self,
            total_packets=total_packets,
            preparation_delay=sender_delay,
            timeout=timeout,
        )

        receiver = Receiver(
            name="Receiver",
            parent=self,
            processing_delay=receiver_delay,
        )

        subnet1 = Subnet1(
            name="Subnet1",
            parent=self,
            seed=seed,
            delay=channel_delay,
        )

        subnet2 = Subnet2(
            name="Subnet2",
            parent=self,
            seed=seed,
            delay=channel_delay,
        )

        # Register components
        self.add_component(sender)
        self.add_component(receiver)
        self.add_component(subnet1)
        self.add_component(subnet2)

        # Define couplings
        # Sender -> Subnet1
        self.add_coupling(sender.output["packet_out"], subnet1.input["in"])

        # Subnet1 -> Receiver
        self.add_coupling(subnet1.output["out"], receiver.input["packet_in"])

        # Receiver -> Subnet2
        self.add_coupling(receiver.output["ack_out"], subnet2.input["in"])

        # Subnet2 -> Sender
        self.add_coupling(subnet2.output["out"], sender.input["ack_in"])