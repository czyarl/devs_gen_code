"""
Offline_File_Transfer: top-level coupled model for offline file transfer simulation.

This coupled model is a pure structural container:
- No boundary ports (portless root).
- No external I/O.
- Composes CommandSource, Sender, Server, Receiver, and four fixed-delay subnets.
- Connects two independent ABP loops:
  Upload:   Sender -> SubnetA1 -> Server -> SubnetA2 -> Sender
  Download: Server -> SubnetB1 -> Receiver -> SubnetB2 -> Server
"""

from xdevs.models import Atomic, Coupled, Port

from .Offline_File_Transfer_libs.CommandSource import CommandSource
from .Offline_File_Transfer_libs.Sender import Sender
from .Offline_File_Transfer_libs.Server import Server
from .Offline_File_Transfer_libs.Receiver import Receiver
from .Offline_File_Transfer_libs.SubnetA1 import SubnetA1
from .Offline_File_Transfer_libs.SubnetA2 import SubnetA2
from .Offline_File_Transfer_libs.SubnetB1 import SubnetB1
from .Offline_File_Transfer_libs.SubnetB2 import SubnetB2


class Offline_File_Transfer(Coupled):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        sender_preparation_delay_ms: float,
        sender_ack_timeout_ms: float,
        server_receiver_processing_delay_ms: float,
        receiver_processing_delay_ms: float,
        subnet_delay_ms: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Children
        command_source = CommandSource(name="command_source", parent=self)

        sender = Sender(
            name="sender",
            parent=self,
            preparation_delay_ms=sender_preparation_delay_ms,
            ack_timeout_ms=sender_ack_timeout_ms,
        )

        server = Server(
            name="server",
            parent=self,
            server_receiver_processing_delay_ms=server_receiver_processing_delay_ms,
        )

        receiver = Receiver(
            name="receiver",
            parent=self,
            processing_delay_ms=receiver_processing_delay_ms,
        )

        subnet_a1 = SubnetA1(name="subnet_a1", parent=self, delay_ms=subnet_delay_ms)
        subnet_a2 = SubnetA2(name="subnet_a2", parent=self, delay_ms=subnet_delay_ms)
        subnet_b1 = SubnetB1(name="subnet_b1", parent=self, delay_ms=subnet_delay_ms)
        subnet_b2 = SubnetB2(name="subnet_b2", parent=self, delay_ms=subnet_delay_ms)

        for comp in (
            command_source,
            sender,
            server,
            receiver,
            subnet_a1,
            subnet_a2,
            subnet_b1,
            subnet_b2,
        ):
            self.add_component(comp)

        # Couplings (per locked topology and child interfaces)

        # Commands routing
        self.add_coupling(
            command_source.output["control_out"],
            sender.input["control_in"],
        )
        self.add_coupling(
            command_source.output["request_out"],
            server.input["request_in"],
        )

        # Upload loop: Sender -> A1 -> Server -> A2 -> Sender
        self.add_coupling(
            sender.output["data_out"],
            subnet_a1.input["data_in"],
        )
        self.add_coupling(
            subnet_a1.output["data_out"],
            server.input["upload_data_in"],
        )
        self.add_coupling(
            server.output["sender_ack_out"],
            subnet_a2.input["ack_in"],
        )
        self.add_coupling(
            subnet_a2.output["ack_out"],
            sender.input["ack_in"],
        )

        # Download loop: Server -> B1 -> Receiver -> B2 -> Server
        self.add_coupling(
            server.output["download_data_out"],
            subnet_b1.input["data_in"],
        )
        self.add_coupling(
            subnet_b1.output["data_out"],
            receiver.input["data_in"],
        )
        self.add_coupling(
            receiver.output["ack_out"],
            subnet_b2.input["ack_in"],
        )
        self.add_coupling(
            subnet_b2.output["ack_out"],
            server.input["receiver_ack_in"],
        )