"""Offline_File_Transfer: top-level coupled model wiring the offline file transfer scenario.

This coupled model is purely structural: it declares no boundary ports and performs
no external I/O. All timing, ABP logic, and stdout JSONL emission are handled by
its atomic/coupled children.
"""

from xdevs.models import Atomic, Coupled, Port

from .Offline_File_Transfer_libs.StdinScheduleSource import StdinScheduleSource
from .Offline_File_Transfer_libs.Sender import Sender
from .Offline_File_Transfer_libs.Server import Server
from .Offline_File_Transfer_libs.Receiver import Receiver
from .Offline_File_Transfer_libs.SubnetA1 import SubnetA1
from .Offline_File_Transfer_libs.SubnetA2 import SubnetA2
from .Offline_File_Transfer_libs.SubnetB1 import SubnetB1
from .Offline_File_Transfer_libs.SubnetB2 import SubnetB2


class Offline_File_Transfer(Coupled):
    """Top-level coupled DEVS model for the offline file transfer simulation."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        link_delay_ms: float,
        sender_preparation_ms: float,
        sender_timeout_ms: float,
        server_receiver_processing_ms: float,
        receiver_processing_ms: float,
    ):
        super().__init__(name)
        self.parent = parent

        # No boundary ports for this top-level coupled model (locked contract).

        # Children
        stdin_source = StdinScheduleSource(name="stdin_source", parent=self)

        sender = Sender(
            name="sender",
            parent=self,
            preparation_ms=sender_preparation_ms,
            timeout_ms=sender_timeout_ms,
        )

        server = Server(
            name="server",
            parent=self,
            receiver_processing_ms=server_receiver_processing_ms,
        )

        receiver = Receiver(
            name="receiver",
            parent=self,
            processing_ms=receiver_processing_ms,
        )

        subnet_a1 = SubnetA1(name="subnet_a1", parent=self, delay_ms=link_delay_ms)
        subnet_a2 = SubnetA2(name="subnet_a2", parent=self, delay_ms=link_delay_ms)
        subnet_b1 = SubnetB1(name="subnet_b1", parent=self, delay_ms=link_delay_ms)
        subnet_b2 = SubnetB2(name="subnet_b2", parent=self, delay_ms=link_delay_ms)

        for comp in (
            stdin_source,
            sender,
            server,
            receiver,
            subnet_a1,
            subnet_a2,
            subnet_b1,
            subnet_b2,
        ):
            self.add_component(comp)

        # Couplings (topology)
        # StdinScheduleSource -> Sender/Server control plane
        self.add_coupling(stdin_source.output["control_out"], sender.input["control_in"])
        self.add_coupling(
            stdin_source.output["request_out"], server.input["download_request_in"]
        )

        # Upload ABP loop: Sender -> SubnetA1 -> Server, ACK back via SubnetA2
        self.add_coupling(sender.output["data_out"], subnet_a1.input["data_in"])
        self.add_coupling(subnet_a1.output["data_out"], server.input["upload_data_in"])

        self.add_coupling(server.output["sender_ack_out"], subnet_a2.input["ack_in"])
        self.add_coupling(subnet_a2.output["ack_out"], sender.input["ack_in"])

        # Download ABP loop: Server -> SubnetB1 -> Receiver, ACK back via SubnetB2
        self.add_coupling(server.output["download_data_out"], subnet_b1.input["data_in"])
        self.add_coupling(subnet_b1.output["data_out"], receiver.input["data_in"])

        self.add_coupling(receiver.output["ack_out"], subnet_b2.input["ack_in"])
        self.add_coupling(subnet_b2.output["ack_out"], server.input["receiver_ack_in"])