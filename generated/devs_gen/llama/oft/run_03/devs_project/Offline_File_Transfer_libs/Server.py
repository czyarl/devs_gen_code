"""Complete pattern: a portless coupled root with one internal connection."""

from xdevs.models import Atomic, Coupled, Port

from .Server_libs.ServerReceiver import ServerReceiver
from .Server_libs.ServerSender import ServerSender


class Server(Coupled):
    """Connect two children without inventing coupled boundary ports."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
    ):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(None, "packet_in"))
        self.add_in_port(Port(None, "download_valve_change"))
        self.add_in_port(Port(None, "packet_out"))
        self.add_out_port(Port(None, "packet_out"))

        server_receiver = ServerReceiver(
            name="ServerReceiver",
            parent=self,
        )
        server_sender = ServerSender(
            name="ServerSender",
            parent=self,
        )
        self.add_component(server_receiver)
        self.add_component(server_sender)

        self.add_coupling(
            self.input["packet_in"],
            server_receiver.input["packet_in"],
        )
        self.add_coupling(
            server_receiver.output["storage_queue"],
            server_sender.input["storage_queue"],
        )
        self.add_coupling(
            self.input["download_valve_change"],
            server_sender.input["download_valve"],
        )
        self.add_coupling(
            server_receiver.output["ack_out"],
            self.output["packet_out"],
        )
        self.add_coupling(
            server_sender.output["packet_out"],
            self.output["packet_out"],
        )