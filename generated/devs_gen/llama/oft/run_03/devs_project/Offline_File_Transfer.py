from xdevs.models import Atomic, Coupled, Port
from .Offline_File_Transfer_libs.Sender import Sender
from .Offline_File_Transfer_libs.Server import Server
from .Offline_File_Transfer_libs.Receiver import Receiver
from .Offline_File_Transfer_libs.Subnet_A import Subnet_A
from .Offline_File_Transfer_libs.Subnet_B import Subnet_B
from .Offline_File_Transfer_libs.InputHandler import InputHandler


class Offline_File_Transfer(Coupled):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulation_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(None, "control_cmd"))
        self.add_in_port(Port(None, "download_valve_change"))
        self.add_out_port(Port(None, "packet_out"))

        sender = Sender(
            name="Sender",
            parent=self,
        )
        server = Server(
            name="Server",
            parent=self,
        )
        receiver = Receiver(
            name="Receiver",
            parent=self,
        )
        subnet_A = Subnet_A(
            name="Subnet_A",
            parent=self,
        )
        subnet_B = Subnet_B(
            name="Subnet_B",
            parent=self,
        )
        input_handler = InputHandler(
            name="InputHandler",
            parent=self,
        )
        self.add_component(sender)
        self.add_component(server)
        self.add_component(receiver)
        self.add_component(subnet_A)
        self.add_component(subnet_B)
        self.add_component(input_handler)

        self.add_coupling(
            input_handler.output["control_cmd"],
            sender.input["control_cmd"],
        )
        self.add_coupling(
            sender.output["packet_out"],
            subnet_A.input["packet_in"],
        )
        self.add_coupling(
            subnet_A.output["packet_out"],
            server.input["packet_in"],
        )
        self.add_coupling(
            server.output["packet_out"],
            subnet_B.input["packet_in"],
        )
        self.add_coupling(
            subnet_B.output["packet_out"],
            receiver.input["packet_in"],
        )
        self.add_coupling(
            input_handler.output["control_cmd"],  # Corrected here
            server.input["download_valve_change"],
        )