"""Complete pattern: a pure coupled container using exact child interfaces."""

from xdevs.models import Atomic, Coupled, Port
from .Server_libs.ServerReceiver import ServerReceiver
from .Server_libs.ServerSender import ServerSender


class Server(Coupled):
    """Connect a receiver and processor without adding active behavior."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "uploaded_packets_in"))
        self.add_out_port(Port(dict, "downloadable_packets_out"))

        server_receiver = ServerReceiver(name="server_receiver", parent=self)
        server_sender = ServerSender(name="server_sender", parent=self)
        self.add_component(server_receiver)
        self.add_component(server_sender)

        self.add_coupling(self.input["uploaded_packets_in"], server_receiver.input["uploaded_packets_in"])
        self.add_coupling(server_receiver.output["ack_out"], server_sender.input["ack_from_receiver"])
        self.add_coupling(server_receiver.output["storage_queue_out"], server_sender.input["storage_queue_in"])
        self.add_coupling(server_sender.output["downloadable_packets_out"], self.output["downloadable_packets_out"])
        self.add_coupling(server_sender.output["ack_out"], server_receiver.input["ack_out"])