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
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulation_time: float = 10000000.0,
        preparation_delay: float = 10000.0,
        timeout_duration: float = 20000.0,
        processing_delay: float = 3000.0,
        link_delay: float = 3000.0,
    ):
        super().__init__(name)
        self.parent = parent

        # Instantiate child components
        input_handler = InputHandler(name="input_handler", parent=self)
        sender = Sender(
            name="sender",
            parent=self,
            preparation_delay=preparation_delay,
            timeout_duration=timeout_duration,
            link_delay=link_delay,
        )
        server = Server(
            name="server",
            parent=self,
            processing_delay=processing_delay,
            link_delay=link_delay,
        )
        receiver = Receiver(
            name="receiver",
            parent=self,
            processing_delay=processing_delay,
            link_delay=link_delay,
        )
        subnet_a1 = SubnetA1(name="subnet_a1", parent=self, delay=link_delay)
        subnet_a2 = SubnetA2(name="subnet_a2", parent=self, delay=link_delay)
        subnet_b1 = SubnetB1(name="subnet_b1", parent=self, delay=link_delay)
        subnet_b2 = SubnetB2(name="subnet_b2", parent=self, delay=link_delay)

        # Register components
        self.add_component(input_handler)
        self.add_component(sender)
        self.add_component(server)
        self.add_component(receiver)
        self.add_component(subnet_a1)
        self.add_component(subnet_a2)
        self.add_component(subnet_b1)
        self.add_component(subnet_b2)

        # Define couplings as per the locked contract
        # Connect InputHandler.control_cmd to Sender.control_cmd.
        self.add_coupling(
            input_handler.output["control_cmd"],
            sender.input["control_cmd"],
        )

        # Connect InputHandler.download_valve_change to Server.download_valve_change.
        self.add_coupling(
            input_handler.output["download_valve_change"],
            server.input["download_valve_change"],
        )

        # Connect Sender.data_to_server to SubnetA1.data_in.
        self.add_coupling(
            sender.output["data_to_server"],
            subnet_a1.input["data_in"],
        )

        # Connect SubnetA1.data_out to Server.data_from_sender.
        self.add_coupling(
            subnet_a1.output["data_out"],
            server.input["data_from_sender"],
        )

        # Connect Server.ack_to_sender to SubnetA2.ack_in.
        self.add_coupling(
            server.output["ack_to_sender"],
            subnet_a2.input["ack_in"],
        )

        # Connect SubnetA2.ack_out to Sender.ack_from_server.
        self.add_coupling(
            subnet_a2.output["ack_out"],
            sender.input["ack_from_server"],
        )

        # Connect Server.data_to_receiver to SubnetB1.data_in.
        self.add_coupling(
            server.output["data_to_receiver"],
            subnet_b1.input["data_in"],
        )

        # Connect SubnetB1.data_out to Receiver.data_from_server.
        self.add_coupling(
            subnet_b1.output["data_out"],
            receiver.input["data_from_server"],
        )

        # Connect Receiver.ack_to_server to SubnetB2.ack_in.
        self.add_coupling(
            receiver.output["ack_to_server"],
            subnet_b2.input["ack_in"],
        )

        # Connect SubnetB2.ack_out to Server.ack_from_receiver.
        self.add_coupling(
            subnet_b2.output["ack_out"],
            server.input["ack_from_receiver"],
        )