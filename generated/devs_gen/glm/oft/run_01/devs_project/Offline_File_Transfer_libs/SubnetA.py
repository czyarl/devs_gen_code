from xdevs.models import Atomic, Coupled, Port


class SubnetA(Atomic):
    """Simulate two independent, reliable, FIFO network channels with a fixed transmission delay."""

    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay

        # Input ports
        self.add_in_port(Port(dict, "in_from_sender"))
        self.add_in_port(Port(dict, "in_from_server"))

        # Output ports
        self.add_out_port(Port(dict, "out_to_server"))
        self.add_out_port(Port(dict, "out_to_sender"))

        # Internal state
        self.queue_a1 = []  # FIFO for data packets (Sender -> Server)
        self.queue_a2 = []  # FIFO for ACK packets (Server -> Sender)
        self.in_flight_a1 = None
        self.in_flight_a2 = None

    def initialize(self):
        self.queue_a1 = []
        self.queue_a2 = []
        self.in_flight_a1 = None
        self.in_flight_a2 = None
        self.passivate("IDLE")

    def _start_next(self):
        """Check queues and schedule internal transition if packets are waiting."""
        # If we are currently processing something, we wait for deltint to clear it.
        # If nothing is in flight, we check queues.
        if self.in_flight_a1 is None and self.queue_a1:
            self.in_flight_a1 = self.queue_a1.pop(0)
            self.hold_in("BUSY", self.delay)
        elif self.in_flight_a2 is None and self.queue_a2:
            self.in_flight_a2 = self.queue_a2.pop(0)
            self.hold_in("BUSY", self.delay)
        elif self.in_flight_a1 is None and self.in_flight_a2 is None:
            self.passivate("IDLE")
        else:
            # Already busy, keep current sigma (handled by caller or logic)
            pass

    def deltext(self, e: float):
        # Handle incoming packets
        for packet in self.input["in_from_sender"].values:
            self.queue_a1.append(dict(packet))

        for packet in self.input["in_from_server"].values:
            self.queue_a2.append(dict(packet))

        # State transition logic based on current phase
        if self.phase == "IDLE":
            # If idle, start processing immediately if queues are not empty
            if self.queue_a1 or self.queue_a2:
                self._start_next()
            # If queues are empty, remain passive (passivate called in _start_next if needed, 
            # but here we just ensure we stay passive if nothing arrived)
            elif not self.queue_a1 and not self.queue_a2:
                self.passivate("IDLE")
        
        elif self.phase == "BUSY":
            # If busy, we must preserve the remaining time for the current in-flight packet.
            # The new arrivals are just buffered.
            remaining = max(0.0, self.ta() - e)
            self.hold_in("BUSY", remaining)

    def lambdaf(self):
        if self.phase == "BUSY":
            # Output the packet that just finished the delay
            if self.in_flight_a1 is not None:
                self.output["out_to_server"].add(dict(self.in_flight_a1))
            elif self.in_flight_a2 is not None:
                self.output["out_to_sender"].add(dict(self.in_flight_a2))

    def deltint(self):
        # Clear the in-flight packet that was just sent
        if self.in_flight_a1 is not None:
            self.in_flight_a1 = None
        elif self.in_flight_a2 is not None:
            self.in_flight_a2 = None

        # Schedule next packet if any
        self._start_next()

    def exit(self):
        pass