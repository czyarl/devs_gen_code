from xdevs.models import Atomic, Coupled, Port


class SubnetB(Atomic):
    """
    Simulates a reliable network link with a fixed propagation delay of 3 seconds
    (3000ms) in both directions between the Server and the Receiver.
    """
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Constants
        self.DELAY_MS = 3000.0
        
        # Input Ports
        self.add_in_port(Port(dict, "in_from_server"))
        self.add_in_port(Port(dict, "in_from_receiver"))
        
        # Output Ports
        self.add_out_port(Port(dict, "out_to_receiver"))
        self.add_out_port(Port(dict, "out_to_server"))
        
        # Internal State
        self.payload = None
        self.target_port = None

    def initialize(self):
        self.payload = None
        self.target_port = None
        self.passivate("IDLE")

    def deltext(self, e):
        # If we are currently delaying a packet, we ignore new inputs (FIFO behavior)
        # and just continue the current delay.
        if self.phase == "DELAYING":
            self.continuef(e)
            return

        # If idle, check for inputs on either port.
        # Priority logic isn't strictly defined for simultaneous arrival, 
        # but we process one at a time to maintain FIFO order.
        if not self.input["in_from_server"].empty():
            for packet in self.input["in_from_server"].values:
                self.payload = dict(packet)
                self.target_port = "out_to_receiver"
                self.hold_in("DELAYING", self.DELAY_MS)
                return
        
        if not self.input["in_from_receiver"].empty():
            for packet in self.input["in_from_receiver"].values:
                self.payload = dict(packet)
                self.target_port = "out_to_server"
                self.hold_in("DELAYING", self.DELAY_MS)
                return
        
        # If no input received, remain passive
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "DELAYING" and self.payload is not None:
            self.output[self.target_port].add(dict(self.payload))

    def deltint(self):
        # After outputting the delayed packet, clear state and go idle
        self.payload = None
        self.target_port = None
        self.passivate("IDLE")

    def exit(self):
        pass