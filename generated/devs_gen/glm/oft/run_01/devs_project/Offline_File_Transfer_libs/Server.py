from xdevs.models import Atomic, Coupled, Port

from .Server_libs.ServerReceiver import ServerReceiver
from .Server_libs.ServerSender import ServerSender


class Server(Coupled):
    """Act as a buffer containing ServerReceiver and ServerSender. Route external packets from SubnetA to ServerReceiver, route ACKs from ServerReceiver to SubnetA, route valid data from ServerReceiver to ServerSender's internal queue, route request commands to ServerSender, route packets from ServerSender to SubnetB, and route ACKs from SubnetB to ServerSender."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Boundary Ports
        self.add_in_port(Port(dict, "upload_in"))
        self.add_in_port(Port(bool, "request_in"))
        self.add_in_port(Port(dict, "download_ack_in"))
        self.add_out_port(Port(dict, "upload_ack_out"))
        self.add_out_port(Port(dict, "download_out"))

        # Components
        receiver = ServerReceiver(name="receiver", parent=self)
        sender = ServerSender(name="sender", parent=self)
        self.add_component(receiver)
        self.add_component(sender)

        # Couplings
        # EIC: External Input to Child Input
        self.add_coupling(self.input["upload_in"], receiver.input["data_in"])
        self.add_coupling(self.input["request_in"], sender.input["request_in"])
        self.add_coupling(self.input["download_ack_in"], sender.input["ack_in"])

        # IC: Child Output to Child Input
        self.add_coupling(receiver.output["storage_out"], sender.input["storage_in"])

        # EOC: Child Output to External Output
        self.add_coupling(receiver.output["ack_out"], self.output["upload_ack_out"])
        self.add_coupling(sender.output["data_out"], self.output["download_out"])