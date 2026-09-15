"""Top-level coupled model ABP_D1: Alternating Bit Protocol scenario assembly.

This coupled model is a pure structural container:
- Instantiates one Sender, one Receiver, and two Subnet channels (forward/backward).
- Wires internal couplings among children.
- No boundary ports and no external I/O in this wrapper.
"""

from xdevs.models import Atomic, Coupled, Port

from .ABP_D1_libs.Sender import Sender
from .ABP_D1_libs.Receiver import Receiver
from .ABP_D1_libs.Subnet import Subnet


class ABP_D1(Coupled):
    """Assemble Sender, Receiver, and two deterministic-loss Subnets."""

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
            sender_delay=float(sender_delay),
            timeout=float(timeout),
        )
        receiver = Receiver(
            name="receiver",
            parent=self,
            receiver_delay=float(receiver_delay),
        )
        subnet_forward = Subnet(
            name="subnet_forward",
            parent=self,
            channel="forward",
            seed=seed,
            channel_delay=float(channel_delay),
        )
        subnet_backward = Subnet(
            name="subnet_backward",
            parent=self,
            channel="backward",
            seed=seed,
            channel_delay=float(channel_delay),
        )

        self.add_component(sender)
        self.add_component(receiver)
        self.add_component(subnet_forward)
        self.add_component(subnet_backward)

        # Internal couplings (no boundary ports in this coupled model)
        self.add_coupling(sender.output["pkt_out"], subnet_forward.input["in_pkt"])
        self.add_coupling(subnet_forward.output["out_pkt"], receiver.input["pkt_in"])
        self.add_coupling(receiver.output["ack_out"], subnet_backward.input["in_pkt"])
        self.add_coupling(subnet_backward.output["out_pkt"], sender.input["ack_in"])