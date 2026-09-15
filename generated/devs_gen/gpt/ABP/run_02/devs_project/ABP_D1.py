from xdevs.models import Atomic, Coupled, Port

from .ABP_D1_libs.Sender import Sender
from .ABP_D1_libs.Receiver import Receiver
from .ABP_D1_libs.DeterministicSubnet import DeterministicSubnet


class ABP_D1(Coupled):
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

        sender = Sender(
            name="sender",
            parent=self,
            total_packets=total_packets,
            timeout=timeout,
            sender_delay=sender_delay,
        )
        receiver = Receiver(
            name="receiver",
            parent=self,
            receiver_delay=receiver_delay,
        )
        subnet_forward = DeterministicSubnet(
            name="subnet_forward",
            parent=self,
            channel="forward",
            seed=seed,
            channel_delay=channel_delay,
        )
        subnet_backward = DeterministicSubnet(
            name="subnet_backward",
            parent=self,
            channel="backward",
            seed=seed,
            channel_delay=channel_delay,
        )

        self.add_component(sender)
        self.add_component(receiver)
        self.add_component(subnet_forward)
        self.add_component(subnet_backward)

        # Sender -> forward subnet -> Receiver
        self.add_coupling(sender.output["data_out"], subnet_forward.input["pkt_in"])
        self.add_coupling(subnet_forward.output["pkt_out"], receiver.input["data_in"])

        # Receiver -> backward subnet -> Sender
        self.add_coupling(receiver.output["ack_out"], subnet_backward.input["pkt_in"])
        self.add_coupling(subnet_backward.output["pkt_out"], sender.input["ack_in"])