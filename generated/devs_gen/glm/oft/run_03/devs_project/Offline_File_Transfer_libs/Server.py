from xdevs.models import Atomic, Coupled, Port

from .Server_libs.ServerReceiver import ServerReceiver
from .Server_libs.ServerSender import ServerSender


class Server(Coupled):
    """Encapsulate ServerReceiver and ServerSender. Route incoming data from SubnetA to ServerReceiver, incoming ACKs from SubnetB to ServerSender, and route outgoing ACKs and data to the appropriate subnets."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Boundary Ports
        self.add_in_port(Port(dict, "data_in"))
        self.add_in_port(Port(dict, "ack_in"))
        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "ack_out"))
        self.add_out_port(Port(dict, "data_out"))

        # Components
        server_receiver = ServerReceiver(name="server_receiver", parent=self)
        server_sender = ServerSender(name="server_sender", parent=self)
        self.add_component(server_receiver)
        self.add_component(server_sender)

        # External Input Couplings (EIC)
        # Forward parent.data_in to ServerReceiver.data_in
        self.add_coupling(self.input["data_in"], server_receiver.input["data_in"])
        
        # Forward parent.request_in to ServerSender.request_in
        self.add_coupling(self.input["request_in"], server_sender.input["request_in"])
        
        # Forward parent.ack_in to ServerSender.ack_in
        self.add_coupling(self.input["ack_in"], server_sender.input["ack_in"])

        # Internal Couplings (IC)
        # Forward ServerReceiver.storage_out to ServerSender.storage_in
        self.add_coupling(server_receiver.output["storage_out"], server_sender.input["storage_in"])

        # External Output Couplings (EOC)
        # Forward ServerReceiver.ack_out to parent.ack_out
        self.add_coupling(server_receiver.output["ack_out"], self.output["ack_out"])
        
        # Forward ServerSender.data_out to parent.data_out
        self.add_coupling(server_sender.output["data_out"], self.output["data_out"])