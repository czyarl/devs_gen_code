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
    """Root coupled model for the Dropbox-like file transfer simulation."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        sender_preparation_delay: float,
        sender_timeout: float,
        server_receiver_processing_delay: float,
        receiver_processing_delay: float,
        subnet_delay: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Instantiate components
        input_handler = InputHandler(name="InputHandler", parent=self)
        
        sender = Sender(
            name="Sender",
            parent=self,
            preparation_delay=sender_preparation_delay,
            timeout=sender_timeout,
        )
        
        server = Server(
            name="Server",
            parent=self,
            server_receiver_processing_delay=server_receiver_processing_delay,
        )
        
        receiver = Receiver(
            name="Receiver",
            parent=self,
            processing_delay=receiver_processing_delay,
        )
        
        subnet_a1 = SubnetA1(name="SubnetA1", parent=self, delay=subnet_delay)
        subnet_a2 = SubnetA2(name="SubnetA2", parent=self, delay=subnet_delay)
        subnet_b1 = SubnetB1(name="SubnetB1", parent=self, delay=subnet_delay)
        subnet_b2 = SubnetB2(name="SubnetB2", parent=self, delay=subnet_delay)

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
        # InputHandler -> Sender
        self.add_coupling(
            input_handler.output["control_out"],
            sender.input["control_in"],
        )
        
        # InputHandler -> Server
        self.add_coupling(
            input_handler.output["request_out"],
            server.input["request_in"],
        )
        
        # Sender -> SubnetA1
        self.add_coupling(
            sender.output["data_out"],
            subnet_a1.input["data_in"],
        )
        
        # SubnetA1 -> Server
        self.add_coupling(
            subnet_a1.output["data_out"],
            server.input["data_in"],
        )
        
        # Server -> SubnetA2
        self.add_coupling(
            server.output["ack_out"],
            subnet_a2.input["ack_in"],
        )
        
        # SubnetA2 -> Sender
        self.add_coupling(
            subnet_a2.output["ack_out"],
            sender.input["ack_in"],
        )
        
        # Server -> SubnetB1
        self.add_coupling(
            server.output["data_out"],
            subnet_b1.input["data_in"],
        )
        
        # SubnetB1 -> Receiver
        self.add_coupling(
            subnet_b1.output["data_out"],
            receiver.input["data_in"],
        )
        
        # Receiver -> SubnetB2
        self.add_coupling(
            receiver.output["ack_out"],
            subnet_b2.input["ack_in"],
        )
        
        # SubnetB2 -> Server
        self.add_coupling(
            subnet_b2.output["ack_out"],
            server.input["ack_in"],
        )