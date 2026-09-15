"""Complete pattern: a pure coupled container using exact child interfaces."""

from xdevs.models import Atomic, Coupled, Port

from .Server_libs.ServerReceiver import ServerReceiver
from .Server_libs.ServerSender import ServerSender


class Server(Coupled):
    """Routes messages internally based on their type; acts as a buffer between Sender and Receiver."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "data_in"))
        self.add_in_port(Port(dict, "download_valve"))
        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "ack_out"))
        self.add_out_port(Port(dict, "data_out"))

        receiver = ServerReceiver(name="ServerReceiver", parent=self, processing_delay=3.0)
        sender = ServerSender(name="ServerSender", parent=self)
        self.add_component(receiver)
        self.add_component(sender)

        self.add_coupling(self.input["data_in"], receiver.input["data_in"])
        self.add_coupling(self.input["download_valve"], sender.input["download_valve"])
        self.add_coupling(self.input["ack_in"], sender.input["ack_in"])
        self.add_coupling(receiver.output["ack_out"], self.output["ack_out"])
        self.add_coupling(sender.output["data_out"], self.output["data_out"])