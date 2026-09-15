"""ABP_D1 coupled model: structural wrapper for Alternating Bit Protocol system.

Topology:
Sender -> ForwardSubnet -> Receiver -> BackwardSubnet -> Sender

This coupled model defines only structure and couplings. All timing, loss,
protocol logic, and JSONL stdout emission are handled by atomic children.
"""

from xdevs.models import Atomic, Coupled, Port

from .ABP_D1_libs.Sender import Sender
from .ABP_D1_libs.Receiver import Receiver
from .ABP_D1_libs.Subnet import Subnet


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

        # No boundary ports (locked contract)

        # Components
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
        forward_subnet = Subnet(
            name="forward_subnet",
            parent=self,
            channel="forward",
            seed=seed,
            channel_delay=channel_delay,
        )
        backward_subnet = Subnet(
            name="backward_subnet",
            parent=self,
            channel="backward",
            seed=seed,
            channel_delay=channel_delay,
        )

        self.add_component(sender)
        self.add_component(receiver)
        self.add_component(forward_subnet)
        self.add_component(backward_subnet)

        # Couplings
        self.add_coupling(sender.output["pkt_out"], forward_subnet.input["msg_in"])
        self.add_coupling(forward_subnet.output["msg_out"], receiver.input["pkt_in"])
        self.add_coupling(receiver.output["ack_out"], backward_subnet.input["msg_in"])
        self.add_coupling(backward_subnet.output["msg_out"], sender.input["ack_in"])