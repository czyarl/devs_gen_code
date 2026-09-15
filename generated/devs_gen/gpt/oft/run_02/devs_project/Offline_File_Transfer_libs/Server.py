from xdevs.models import Atomic, Coupled, Port

from .Server_libs.ServerReceiver import ServerReceiver
from .Server_libs.ServerSender import ServerSender


class Server(Coupled):
    def __init__(self, name: str, parent: Coupled | None, server_receiver_processing_ms: float):
        super().__init__(name)
        self.parent = parent

        # Boundary input ports
        self.add_in_port(Port(dict, "upload_data_in"))
        self.add_in_port(Port(dict, "request_in"))
        self.add_in_port(Port(dict, "receiver_ack_in"))

        # Boundary output ports
        self.add_out_port(Port(dict, "sender_ack_out"))
        self.add_out_port(Port(dict, "download_data_out"))

        # Children
        server_receiver = ServerReceiver(
            name="server_receiver",
            parent=self,
            processing_ms=server_receiver_processing_ms,
        )
        server_sender = ServerSender(
            name="server_sender",
            parent=self,
        )

        self.add_component(server_receiver)
        self.add_component(server_sender)

        # Couplings (EIC)
        self.add_coupling(self.input["upload_data_in"], server_receiver.input["upload_data_in"])
        self.add_coupling(self.input["request_in"], server_sender.input["request_in"])
        self.add_coupling(self.input["receiver_ack_in"], server_sender.input["receiver_ack_in"])

        # Couplings (IC)
        self.add_coupling(server_receiver.output["enqueue_out"], server_sender.input["enqueue_in"])

        # Couplings (EOC)
        self.add_coupling(server_receiver.output["sender_ack_out"], self.output["sender_ack_out"])
        self.add_coupling(server_sender.output["download_data_out"], self.output["download_data_out"])