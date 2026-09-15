from xdevs.models import Atomic, Coupled, Port
from .Offline_File_Transfer_libs.InputHandler import InputHandler
from .Offline_File_Transfer_libs.Sender import Sender
from .Offline_File_Transfer_libs.Server import Server
from .Offline_File_Transfer_libs.Receiver import Receiver
from .Offline_File_Transfer_libs.SubnetA1 import SubnetA1
from .Offline_File_Transfer_libs.SubnetA2 import SubnetA2
from .Offline_File_Transfer_libs.SubnetB1 import SubnetB1
from .Offline_File_Transfer_libs.SubnetB2 import SubnetB2

class Offline_File_Transfer(Coupled):
    """Orchestrates a file transfer simulation involving upload and download flows with alternating bit protocol between Sender, Server, and Receiver through reliable subnets."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulation_time: float = 10000000.0,
    ):
        super().__init__(name)
        self.parent = parent

        # Create child components
        input_handler = InputHandler(name="InputHandler", parent=self)
        sender = Sender(name="Sender", parent=self)
        server = Server(name="Server", parent=self)
        receiver = Receiver(name="Receiver", parent=self)
        subnet_a1 = SubnetA1(name="SubnetA1", parent=self, delay=3.0)
        subnet_a2 = SubnetA2(name="SubnetA2", parent=self, delay=3.0)
        subnet_b1 = SubnetB1(name="SubnetB1", parent=self, delay=3.0)
        subnet_b2 = SubnetB2(name="SubnetB2", parent=self, delay=3.0)

        # Register components
        self.add_component(input_handler)
        self.add_component(sender)
        self.add_component(server)
        self.add_component(receiver)
        self.add_component(subnet_a1)
        self.add_component(subnet_a2)
        self.add_component(subnet_b1)
        self.add_component(subnet_b2)

        # Define couplings
        # InputHandler to Sender
        self.add_coupling(input_handler.output["control_cmd"], sender.input["control"])

        # InputHandler to Server
        self.add_coupling(input_handler.output["download_valve_change"], server.input["download_valve"])

        # Sender to SubnetA1
        self.add_coupling(sender.output["data"], subnet_a1.input["data_in"])

        # SubnetA1 to Server
        self.add_coupling(subnet_a1.output["data_out"], server.input["data"])

        # Server to SubnetA2
        self.add_coupling(server.output["ack"], subnet_a2.input["ack_in"])

        # SubnetA2 to Sender
        self.add_coupling(subnet_a2.output["ack_out"], sender.input["ack"])

        # Server to SubnetB1
        self.add_coupling(server.output["data"], subnet_b1.input["data_in"])

        # SubnetB1 to Receiver
        self.add_coupling(subnet_b1.output["data_out"], receiver.input["data"])

        # Receiver to SubnetB2
        self.add_coupling(receiver.output["ack"], subnet_b2.input["ack_in"])

        # SubnetB2 to Server
        self.add_coupling(subnet_b2.output["ack_out"], server.input["ack"])