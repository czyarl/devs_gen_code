"""Complete pattern: a pure coupled container using exact child interfaces."""

from xdevs.models import Atomic, Coupled, Port

from .Server_libs.ServerReceiver import ServerReceiver
from .Server_libs.ServerSender import ServerSender


class Server(Coupled):
    """Acts as a buffer between Sender and Receiver, managing data flow through internal ServerReceiver and ServerSender components."""

    def __init__(self, name: str, parent: Coupled | None, processing_delay: float, link_delay: float):
        super().__init__(name)
        self.parent = parent

        # Register boundary ports
        self.add_in_port(Port(dict, "data_from_sender"))
        self.add_in_port(Port(dict, "download_valve_change"))
        self.add_in_port(Port(dict, "ack_from_receiver"))
        self.add_out_port(Port(dict, "ack_to_sender"))
        self.add_out_port(Port(dict, "data_to_receiver"))

        # Instantiate child components
        receiver = ServerReceiver(
            name="server_receiver",
            parent=self,
            processing_delay=processing_delay,
        )
        sender = ServerSender(
            name="server_sender",
            parent=self,
        )
        self.add_component(receiver)
        self.add_component(sender)

        # Define couplings
        # EIC: Forward parent.data_from_sender to ServerReceiver.data_from_sender
        self.add_coupling(self.input["data_from_sender"], receiver.input["data_from_sender"])

        # EIC: Forward parent.download_valve_change to ServerSender.download_valve_change
        self.add_coupling(self.input["download_valve_change"], sender.input["download_valve_change"])

        # EIC: Forward parent.ack_from_receiver to ServerSender.ack_from_receiver
        self.add_coupling(self.input["ack_from_receiver"], sender.input["ack_from_receiver"])

        # IC: Forward ServerReceiver.ack_to_sender to parent.ack_to_sender
        self.add_coupling(receiver.output["ack_to_sender"], self.output["ack_to_sender"])

        # IC: Forward ServerSender.data_to_receiver to parent.data_to_receiver
        self.add_coupling(sender.output["data_to_receiver"], self.output["data_to_receiver"])

        # IC: Forward ServerSender.ack_to_receiver to parent.ack_to_sender
        self.add_coupling(sender.output["ack_to_receiver"], self.output["ack_to_sender"])