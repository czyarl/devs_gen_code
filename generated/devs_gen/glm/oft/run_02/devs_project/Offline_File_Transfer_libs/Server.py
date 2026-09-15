from xdevs.models import Atomic, Coupled, Port

from .Server_libs.ServerReceiver import ServerReceiver
from .Server_libs.ServerSender import ServerSender


class Server(Coupled):
    """Coupled boundary for the Server. Contains ServerReceiver and ServerSender. Routes data from Sender to ServerReceiver, ACKs from ServerReceiver to Sender, 'request' commands to ServerSender, data from ServerSender to Receiver, and ACKs from Receiver to ServerSender."""

    def __init__(self, name: str, parent: Coupled | None, server_receiver_processing_delay: float):
        super().__init__(name)
        self.parent = parent

        # Boundary Ports
        self.add_in_port(Port(dict, "data_in"))
        self.add_in_port(Port(int, "request_in"))
        self.add_in_port(Port(int, "ack_in"))
        self.add_out_port(Port(int, "ack_out"))
        self.add_out_port(Port(dict, "data_out"))

        # Components
        server_receiver = ServerReceiver(
            name="ServerReceiver",
            parent=self,
            processing_delay=server_receiver_processing_delay,
        )
        server_sender = ServerSender(
            name="ServerSender",
            parent=self,
        )
        self.add_component(server_receiver)
        self.add_component(server_sender)

        # Couplings
        # EIC: External Input to Child Input
        self.add_coupling(self.input["data_in"], server_receiver.input["data_in"])
        self.add_coupling(self.input["request_in"], server_sender.input["request_in"])
        self.add_coupling(self.input["ack_in"], server_sender.input["ack_in"])

        # IC: Child Output to Child Input
        self.add_coupling(server_receiver.output["storage_out"], server_sender.input["storage_in"])

        # EOC: Child Output to External Output
        self.add_coupling(server_receiver.output["ack_out"], self.output["ack_out"])
        self.add_coupling(server_sender.output["data_out"], self.output["data_out"])