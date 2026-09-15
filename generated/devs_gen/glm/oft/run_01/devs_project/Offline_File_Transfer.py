from xdevs.models import Atomic, Coupled, Port

from .Offline_File_Transfer_libs.InputSource import InputSource
from .Offline_File_Transfer_libs.Sender import Sender
from .Offline_File_Transfer_libs.Server import Server
from .Offline_File_Transfer_libs.Receiver import Receiver
from .Offline_File_Transfer_libs.SubnetA import SubnetA
from .Offline_File_Transfer_libs.SubnetB import SubnetB


class Offline_File_Transfer(Coupled):
    """Coordinate the Dropbox-like file transfer simulation by routing control and request commands from InputSource to Sender and Server, and connecting the two ABP loops (Sender-Server and Server-Receiver) via SubnetA and SubnetB."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Instantiate components
        input_source = InputSource(name="InputSource", parent=self)
        sender = Sender(name="Sender", parent=self)
        server = Server(name="Server", parent=self)
        receiver = Receiver(name="Receiver", parent=self)
        subnet_a = SubnetA(name="SubnetA", parent=self, delay=3000.0)
        subnet_b = SubnetB(name="SubnetB", parent=self, delay=3000.0)

        # Register components
        self.add_component(input_source)
        self.add_component(sender)
        self.add_component(server)
        self.add_component(receiver)
        self.add_component(subnet_a)
        self.add_component(subnet_b)

        # Define couplings
        # Connect InputSource.control_out to Sender.control_in.
        self.add_coupling(input_source.output["control_out"], sender.input["control_in"])

        # Connect InputSource.request_out to Server.request_in.
        self.add_coupling(input_source.output["request_out"], server.input["request_in"])

        # Connect Sender.data_out to SubnetA.in_from_sender.
        self.add_coupling(sender.output["data_out"], subnet_a.input["in_from_sender"])

        # Connect SubnetA.out_to_sender to Sender.ack_in.
        self.add_coupling(subnet_a.output["out_to_sender"], sender.input["ack_in"])

        # Connect SubnetA.out_to_server to Server.upload_in.
        self.add_coupling(subnet_a.output["out_to_server"], server.input["upload_in"])

        # Connect Server.upload_ack_out to SubnetA.in_from_server.
        self.add_coupling(server.output["upload_ack_out"], subnet_a.input["in_from_server"])

        # Connect Server.download_out to SubnetB.in_from_server.
        self.add_coupling(server.output["download_out"], subnet_b.input["in_from_server"])

        # Connect SubnetB.out_to_server to Server.download_ack_in.
        self.add_coupling(subnet_b.output["out_to_server"], server.input["download_ack_in"])

        # Connect SubnetB.out_to_receiver to Receiver.data_in.
        self.add_coupling(subnet_b.output["out_to_receiver"], receiver.input["data_in"])

        # Connect Receiver.ack_out to SubnetB.in_from_receiver.
        self.add_coupling(receiver.output["ack_out"], subnet_b.input["in_from_receiver"])