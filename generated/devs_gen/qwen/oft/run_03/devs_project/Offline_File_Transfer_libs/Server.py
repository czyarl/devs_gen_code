"""Server coupled model implementing the file transfer simulation logic."""

from xdevs.models import Atomic, Coupled, Port

from .Server_libs.ServerReceiver import ServerReceiver
from .Server_libs.ServerSender import ServerSender


class Server(Coupled):
    """Routes data packets from Sender to ServerReceiver and manages the download flow from ServerSender to Receiver."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Add boundary ports
        self.add_in_port(Port(dict, "data"))
        self.add_in_port(Port(dict, "download_valve"))
        self.add_in_port(Port(dict, "ack"))
        self.add_out_port(Port(dict, "ack"))
        self.add_out_port(Port(dict, "data"))

        # Create child components
        receiver = ServerReceiver(name="ServerReceiver", parent=self)
        sender = ServerSender(name="ServerSender", parent=self)
        self.add_component(receiver)
        self.add_component(sender)

        # Define couplings
        # Forward parent.data to ServerReceiver.data
        self.add_coupling(self.input["data"], receiver.input["data"])

        # Forward ServerReceiver.ack to parent.ack
        self.add_coupling(receiver.output["ack"], self.output["ack"])

        # Forward parent.download_valve to ServerSender.download_valve
        self.add_coupling(self.input["download_valve"], sender.input["download_valve"])

        # Forward parent.data to ServerSender.data
        self.add_coupling(self.input["data"], sender.input["data"])

        # Forward ServerSender.ack to parent.ack
        self.add_coupling(sender.output["ack"], self.output["ack"])

        # Forward ServerSender.data to parent.data
        self.add_coupling(sender.output["data"], self.output["data"])