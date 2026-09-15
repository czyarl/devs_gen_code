from xdevs.models import Atomic, Coupled, Port


class SubnetA(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Define Input Ports
        self.add_in_port(Port(dict, "in_from_sender"))
        self.add_in_port(Port(dict, "in_from_server"))
        
        # Define Output Ports
        self.add_out_port(Port(dict, "out_to_server"))
        self.add_out_port(Port(dict, "out_to_sender"))
        
        # Internal State
        self.packet_to_forward = None
        self.target_port = None
        self.delay = 3.0  # Fixed 3s delay as per requirements

    def initialize(self):
        self.packet_to_forward = None
        self.target_port = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        # If currently delaying a packet, preserve remaining time.
        # Due to the Stop-and-Wait nature of the ABP protocol (Sender waits for ACK),
        # SubnetA will not receive concurrent traffic on the same channel.
        # Thus, a single buffer is sufficient for reliable FIFO behavior in this context.
        if self.phase == "DELAYING":
            self.continuef(e)
            return

        # Check inputs from Sender
        for packet in self.input["in_from_sender"].values:
            self.packet_to_forward = dict(packet)
            self.target_port = "out_to_server"
            self.hold_in("DELAYING", self.delay)
            return
            
        # Check inputs from Server
        for packet in self.input["in_from_server"].values:
            self.packet_to_forward = dict(packet)
            self.target_port = "out_to_sender"
            self.hold_in("DELAYING", self.delay)
            return
            
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "DELAYING" and self.packet_to_forward is not None and self.target_port:
            self.output[self.target_port].add(dict(self.packet_to_forward))

    def deltint(self):
        self.packet_to_forward = None
        self.target_port = None
        self.passivate("IDLE")

    def exit(self):
        pass