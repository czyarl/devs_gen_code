from xdevs.models import Atomic, Coupled, Port

from .Server_libs.ServerReceiver import ServerReceiver
from .Server_libs.ServerSender import ServerSender


class Server(Coupled):
    """
    Coupled Server subsystem.

    Responsibilities (structural only):
      - Route upload packets to ServerReceiver (ingress ABP termination).
      - Route Sender ACKs from ServerReceiver to the Server boundary.
      - Route accepted packets from ServerReceiver into ServerSender storage.
      - Route download valve toggles and Receiver ACKs to ServerSender.
      - Route download packets from ServerSender to the Server boundary.

    All stdout JSONL events are emitted by the atomic children.
    """

    def __init__(self, name: str, parent: Coupled | None, receiver_processing_ms: float):
        super().__init__(name)
        self.parent = parent

        # Boundary ports (locked contract)
        self.add_in_port(Port(dict, "upload_data_in"))
        self.add_in_port(Port(dict, "download_request_in"))
        self.add_in_port(Port(dict, "receiver_ack_in"))

        self.add_out_port(Port(dict, "sender_ack_out"))
        self.add_out_port(Port(dict, "download_data_out"))

        # Children
        server_receiver = ServerReceiver(
            name="server_receiver",
            parent=self,
            processing_ms=receiver_processing_ms,
        )
        server_sender = ServerSender(
            name="server_sender",
            parent=self,
        )

        self.add_component(server_receiver)
        self.add_component(server_sender)

        # Couplings (EIC / IC / EOC)
        self.add_coupling(self.input["upload_data_in"], server_receiver.input["upload_data_in"])
        self.add_coupling(server_receiver.output["sender_ack_out"], self.output["sender_ack_out"])
        self.add_coupling(server_receiver.output["storage_push_out"], server_sender.input["storage_push_in"])

        self.add_coupling(self.input["download_request_in"], server_sender.input["download_request_in"])
        self.add_coupling(self.input["receiver_ack_in"], server_sender.input["receiver_ack_in"])
        self.add_coupling(server_sender.output["download_data_out"], self.output["download_data_out"])