"""Complete File Transfer Scenario using xDEVS."""

from xdevs.models import Atomic, Coupled, Port
from .Offline_File_Transfer_libs.Sender import Sender
from .Offline_File_Transfer_libs.Server import Server
from .Offline_File_Transfer_libs.Receiver import Receiver
from .Offline_File_Transfer_libs.SubnetA import SubnetA
from .Offline_File_Transfer_libs.SubnetB import SubnetB


class Offline_File_Transfer(Coupled):
    """Simulate a 'Dropbox-like' synchronization flow using two independent
    Alternating Bit Protocol (ABP) loops."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulation_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "control_cmd"))
        self.add_out_port(Port(dict, "download_valve_change"))

        sender = Sender(name="Sender", parent=self, simulation_time=simulation_time)
        server = Server(name="Server", parent=self, simulation_time=simulation_time)
        receiver = Receiver(name="Receiver", parent=self, simulation_time=simulation_time)
        subnet_A = SubnetA(name="SubnetA", parent=self)
        subnet_B = SubnetB(name="SubnetB", parent=self)

        self.add_component(sender)
        self.add_component(server)
        self.add_component(receiver)
        self.add_component(subnet_A)
        self.add_component(subnet_B)

        self.add_coupling(self.input["control_cmd"], sender.input["control_cmd"])
        self.add_coupling(sender.output["data_out"], subnet_A.input["data_in"])
        self.add_coupling(subnet_A.output["data_out"], server.input["uploaded_packets_in"])
        self.add_coupling(server.output["downloadable_packets_out"], subnet_B.input["data_in"])
        self.add_coupling(subnet_B.output["data_out"], receiver.input["data_in"])
        self.add_coupling(receiver.output["ack_out"], server.input["ack_out"])
        self.add_coupling(server.output["ack_out"], sender.input["ack_in"])