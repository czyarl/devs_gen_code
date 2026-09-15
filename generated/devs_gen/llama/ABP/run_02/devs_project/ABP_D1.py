from xdevs.models import Atomic, Coupled, Port
from .ABP_D1_libs.Sender import Sender
from .ABP_D1_libs.Receiver import Receiver
from .ABP_D1_libs.Subnet1 import Subnet1
from .ABP_D1_libs.Subnet2 import Subnet2


class ABP_D1(Coupled):
    """Top-level coupled model for ABP_D1. Routes packets through Sender, Receiver, and Subnets."""

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

        self.add_in_port(Port(None, "initial_signal"))
        self.add_out_port(Port(None, "dummy"))

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

        self.add_component(sender)
        self.add_component(receiver)
        self.add_component(subnet1)
        self.add_component(subnet2)

        self.add_coupling(
            sender.output["packet_out"],
            subnet1.input["packet_in"],
        )
        self.add_coupling(
            subnet1.output["packet_out"],
            receiver.input["packet_in"],
        )
        self.add_coupling(
            receiver.output["ack_out"],
            subnet2.input["packet_in"],
        )
        self.add_coupling(
            subnet2.output["packet_out"],
            sender.input["initial_signal"],
        )