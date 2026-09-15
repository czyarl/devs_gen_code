import argparse
import sys
import json
import logging
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Global simulation clock
sim_clock = SimulationClock(0)

# Helper to convert time string to milliseconds
def parse_time(time_str):
    h, m, s, ms = map(int, time_str.split(':'))
    return (h * 3600 + m * 60 + s) * 1000 + ms

# Helper to log to stderr
def log_stderr(msg):
    print(msg, file=sys.stderr)

# Event logging function
def log_event(timestamp, model, event_type, val):
    event = {
        "timestamp_ms": timestamp,
        "model": model,
        "type": event_type,
        "val": val
    }
    print(json.dumps(event), file=sys.stdout, flush=True)

# Sender Model (Uploader)
class Sender(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(int, "control"))
        self.add_out_port(Port(dict, "to_server"))
        self.add_in_port(Port(dict, "ack_from_server"))
        self.add_out_port(Port(dict, "preparation_started"))
        self.add_out_port(Port(dict, "packet_sent"))
        self.add_out_port(Port(dict, "ack_received"))
        self.add_out_port(Port(dict, "timeout"))

        # State
        self.total_packets_to_send = 0
        self.packets_remaining = 0
        self.seq = 1
        self.bit = 0
        self.is_retransmitting = False
        self.timer = None

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        # Output only
        pass

    def deltint(self):
        if self.phase == "IDLE":
            self.hold_in("IDLE", 0)
        elif self.phase == "PREPARING":
            # Send preparation event
            self.output["preparation_started"].add({"duration": 10000})
            self.hold_in("WAITING_FOR_ACK", 10000)
        elif self.phase == "WAITING_FOR_ACK":
            # Timeout
            self.output["timeout"].add({"seq": self.seq})
            self.hold_in("IDLE", 0)
        elif self.phase == "SENDING_PACKET":
            self.output["packet_sent"].add({"seq": self.seq, "bit": self.bit, "is_retry": self.is_retransmitting})
            self.hold_in("WAITING_FOR_ACK", 20000)

    def deltext(self, e):
        if self.phase == "IDLE":
            if "control" in self.input:
                added = self.input["control"].values[0]
                self.total_packets_to_send += added
                self.packets_remaining = self.total_packets_to_send
                log_event(sim_clock.time(), "sender", "control_cmd", {"added": added, "total_remaining": self.packets_remaining})
                self.hold_in("PREPARING", 0)
            else:
                self.hold_in("IDLE", 0)
        elif self.phase == "PREPARING":
            self.hold_in("SENDING_PACKET", 0)
        elif self.phase == "SENDING_PACKET":
            # Handle ACK
            if "ack_from_server" in self.input:
                ack = self.input["ack_from_server"].values[0]
                if ack["bit"] == self.bit:
                    self.output["ack_received"].add({"bit": self.bit})
                    self.packets_remaining -= 1
                    if self.packets_remaining > 0:
                        self.seq += 1
                        self.bit = 1 - self.bit
                        self.is_retransmitting = False
                        self.hold_in("PREPARING", 0)
                    else:
                        self.hold_in("IDLE", 0)
                else:
                    # Duplicate ACK, retransmit
                    self.is_retransmitting = True
                    self.hold_in("SENDING_PACKET", 0)
            else:
                self.hold_in("SENDING_PACKET", 0)
        elif self.phase == "WAITING_FOR_ACK":
            # Handle ACK
            if "ack_from_server" in self.input:
                ack = self.input["ack_from_server"].values[0]
                if ack["bit"] == self.bit:
                    self.output["ack_received"].add({"bit": self.bit})
                    self.packets_remaining -= 1
                    if self.packets_remaining > 0:
                        self.seq += 1
                        self.bit = 1 - self.bit
                        self.is_retransmitting = False
                        self.hold_in("PREPARING", 0)
                    else:
                        self.hold_in("IDLE", 0)
                else:
                    # Duplicate ACK, retransmit
                    self.is_retransmitting = True
                    self.hold_in("SENDING_PACKET", 0)
            else:
                self.hold_in("WAITING_FOR_ACK", 20000)

    def exit(self):
        pass

# Server Receiver Model
class ServerReceiver(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "from_sender"))
        self.add_out_port(Port(dict, "ack_to_sender"))
        self.add_out_port(Port(dict, "packet_received"))
        self.add_out_port(Port(dict, "ack_sent_to_sender"))
        self.add_out_port(Port(dict, "to_server_sender"))

        # State
        self.expected_bit = 0
        self.storage_queue = deque()

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        # Output only
        pass

    def deltint(self):
        if self.phase == "IDLE":
            self.hold_in("IDLE", 0)
        elif self.phase == "PROCESSING":
            # Send packet_received event
            self.output["packet_received"].add({"seq": self.current_packet["seq"], "bit": self.current_packet["bit"]})
            # Simulate 3s delay
            self.hold_in("SENDING_ACK", 3000)
        elif self.phase == "SENDING_ACK":
            # Send ACK
            self.output["ack_sent_to_sender"].add({"bit": self.expected_bit})
            # Send packet to server sender
            self.output["to_server_sender"].add(self.current_packet)
            self.hold_in("IDLE", 0)

    def deltext(self, e):
        if self.phase == "IDLE":
            if "from_sender" in self.input:
                self.current_packet = self.input["from_sender"].values[0]
                self.output["packet_received"].add({"seq": self.current_packet["seq"], "bit": self.current_packet["bit"]})
                self.hold_in("PROCESSING", 0)
            else:
                self.hold_in("IDLE", 0)
        elif self.phase == "PROCESSING":
            self.hold_in("PROCESSING", 3000)
        elif self.phase == "SENDING_ACK":
            self.hold_in("SENDING_ACK", 0)

    def exit(self):
        pass

# Server Sender Model
class ServerSender(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "from_server_receiver"))
        self.add_in_port(Port(int, "download_valve"))
        self.add_out_port(Port(dict, "to_receiver"))
        self.add_in_port(Port(dict, "ack_from_receiver"))
        self.add_out_port(Port(dict, "packet_forwarded"))
        self.add_out_port(Port(dict, "ack_received_from_receiver"))
        self.add_out_port(Port(dict, "download_valve_change"))

        # State
        self.download_allowed = False
        self.storage_queue = deque()
        self.is_sending = False
        self.current_packet = None
        self.current_bit = 0

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        # Output only
        pass

    def deltint(self):
        if self.phase == "IDLE":
            self.hold_in("IDLE", 0)
        elif self.phase == "SENDING_PACKET":
            self.output["packet_forwarded"].add({"seq": self.current_packet["seq"], "bit": self.current_packet["bit"]})
            self.hold_in("WAITING_FOR_ACK", 20000)
        elif self.phase == "WAITING_FOR_ACK":
            self.hold_in("IDLE", 0)

    def deltext(self, e):
        if self.phase == "IDLE":
            if "download_valve" in self.input:
                allowed = self.input["download_valve"].values[0]
                self.download_allowed = bool(allowed)
                log_event(sim_clock.time(), "server_sender", "download_valve_change", {"allowed": self.download_allowed})
                self.output["download_valve_change"].add({"allowed": self.download_allowed})

            if "from_server_receiver" in self.input:
                self.storage_queue.append(self.input["from_server_receiver"].values[0])

            if self.download_allowed and self.storage_queue:
                self.current_packet = self.storage_queue.popleft()
                self.output["packet_forwarded"].add({"seq": self.current_packet["seq"], "bit": self.current_packet["bit"]})
                self.hold_in("SENDING_PACKET", 0)
            else:
                self.hold_in("IDLE", 0)
        elif self.phase == "SENDING_PACKET":
            if "ack_from_receiver" in self.input:
                ack = self.input["ack_from_receiver"].values[0]
                self.output["ack_received_from_receiver"].add({"bit": ack["bit"]})
                self.hold_in("IDLE", 0)
            else:
                self.hold_in("SENDING_PACKET", 20000)
        elif self.phase == "WAITING_FOR_ACK":
            if "ack_from_receiver" in self.input:
                ack = self.input["ack_from_receiver"].values[0]
                self.output["ack_received_from_receiver"].add({"bit": ack["bit"]})
                self.hold_in("IDLE", 0)
            else:
                self.hold_in("WAITING_FOR_ACK", 20000)

    def exit(self):
        pass

# Receiver Model
class Receiver(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "from_server"))
        self.add_out_port(Port(dict, "ack_sent"))
        self.add_out_port(Port(dict, "processing_started"))

        # State
        self.current_packet = None

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        # Output only
        pass

    def deltint(self):
        if self.phase == "IDLE":
            self.hold_in("IDLE", 0)
        elif self.phase == "PROCESSING":
            self.output["processing_started"].add({"seq": self.current_packet["seq"], "duration": 10000})
            self.hold_in("SENDING_ACK", 10000)
        elif self.phase == "SENDING_ACK":
            self.output["ack_sent"].add({"bit": self.current_packet["bit"]})
            self.hold_in("IDLE", 0)

    def deltext(self, e):
        if self.phase == "IDLE":
            if "from_server" in self.input:
                self.current_packet = self.input["from_server"].values[0]
                self.hold_in("PROCESSING", 0)
            else:
                self.hold_in("IDLE", 0)
        elif self.phase == "PROCESSING":
            self.hold_in("PROCESSING", 10000)
        elif self.phase == "SENDING_ACK":
            self.hold_in("SENDING_ACK", 0)

    def exit(self):
        pass

# Subnet Models
class SubnetA1(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "from_sender"))
        self.add_out_port(Port(dict, "to_server"))
        self.delay = 3000

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.phase == "SENDING":
            self.output["to_server"].add(self.current_packet)
        self.hold_in("IDLE", 0)

    def deltint(self):
        self.hold_in("IDLE", 0)

    def deltext(self, e):
        if self.phase == "IDLE":
            if "from_sender" in self.input:
                self.current_packet = self.input["from_sender"].values[0]
                self.hold_in("SENDING", 0)
            else:
                self.hold_in("IDLE", 0)

    def exit(self):
        pass

class SubnetA2(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "from_server"))
        self.add_out_port(Port(dict, "to_sender"))
        self.delay = 3000

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.phase == "SENDING":
            self.output["to_sender"].add(self.current_packet)
        self.hold_in("IDLE", 0)

    def deltint(self):
        self.hold_in("IDLE", 0)

    def deltext(self, e):
        if self.phase == "IDLE":
            if "from_server" in self.input:
                self.current_packet = self.input["from_server"].values[0]
                self.hold_in("SENDING", 0)
            else:
                self.hold_in("IDLE", 0)

    def exit(self):
        pass

class SubnetB1(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "from_server"))
        self.add_out_port(Port(dict, "to_receiver"))
        self.delay = 3000

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.phase == "SENDING":
            self.output["to_receiver"].add(self.current_packet)
        self.hold_in("IDLE", 0)

    def deltint(self):
        self.hold_in("IDLE", 0)

    def deltext(self, e):
        if self.phase == "IDLE":
            if "from_server" in self.input:
                self.current_packet = self.input["from_server"].values[0]
                self.hold_in("SENDING", 0)
            else:
                self.hold_in("IDLE", 0)

    def exit(self):
        pass

class SubnetB2(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "from_receiver"))
        self.add_out_port(Port(dict, "to_server"))
        self.delay = 3000

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.phase == "SENDING":
            self.output["to_server"].add(self.current_packet)
        self.hold_in("IDLE", 0)

    def deltint(self):
        self.hold_in("IDLE", 0)

    def deltext(self, e):
        if self.phase == "IDLE":
            if "from_receiver" in self.input:
                self.current_packet = self.input["from_receiver"].values[0]
                self.hold_in("SENDING", 0)
            else:
                self.hold_in("IDLE", 0)

    def exit(self):
        pass

# System Model
class System(Coupled):
    def __init__(self, name, parent, simulate_time):
        super().__init__(name)
        self.parent = parent

        # Components
        self.sender = Sender("sender", self)
        self.server_receiver = ServerReceiver("server_receiver", self)
        self.server_sender = ServerSender("server_sender", self)
        self.receiver = Receiver("receiver", self)
        self.subnet_a1 = SubnetA1("subnet_a1", self)
        self.subnet_a2 = SubnetA2("subnet_a2", self)
        self.subnet_b1 = SubnetB1("subnet_b1", self)
        self.subnet_b2 = SubnetB2("subnet_b2", self)

        # Add components
        self.add_component(self.sender)
        self.add_component(self.server_receiver)
        self.add_component(self.server_sender)
        self.add_component(self.receiver)
        self.add_component(self.subnet_a1)
        self.add_component(self.subnet_a2)
        self.add_component(self.subnet_b1)
        self.add_component(self.subnet_b2)

        # Couplings
        # Sender to Subnet A1
        self.add_coupling(self.sender.output["to_server"], self.subnet_a1.input["from_sender"])
        # Subnet A1 to Server Receiver
        self.add_coupling(self.subnet_a1.output["to_server"], self.server_receiver.input["from_sender"])
        # Server Receiver to Subnet A2
        self.add_coupling(self.server_receiver.output["to_server_sender"], self.subnet_a2.input["from_server"])
        # Subnet A2 to Sender
        self.add_coupling(self.subnet_a2.output["to_sender"], self.sender.input["ack_from_server"])
        # Server Receiver to Server Sender
        self.add_coupling(self.server_receiver.output["to_server_sender"], self.server_sender.input["from_server_receiver"])
        # Server Sender to Subnet B1
        self.add_coupling(self.server_sender.output["to_receiver"], self.subnet_b1.input["from_server"])
        # Subnet B1 to Receiver
        self.add_coupling(self.subnet_b1.output["to_receiver"], self.receiver.input["from_server"])
        # Receiver to Subnet B2
        self.add_coupling(self.receiver.output["ack_sent"], self.subnet_b2.input["from_receiver"])
        # Subnet B2 to Server Sender
        self.add_coupling(self.subnet_b2.output["to_server"], self.server_sender.input["ack_from_receiver"])

        # Control inputs
        self.add_coupling(self.sender.input["control"], self.input["control"])
        self.add_coupling(self.server_sender.input["download_valve"], self.input["download_valve"])

        # Output
        self.add_coupling(self.sender.output["preparation_started"], self.output["preparation_started"])
        self.add_coupling(self.sender.output["packet_sent"], self.output["packet_sent"])
        self.add_coupling(self.sender.output["ack_received"], self.output["ack_received"])
        self.add_coupling(self.sender.output["timeout"], self.output["timeout"])
        self.add_coupling(self.server_receiver.output["packet_received"], self.output["packet_received"])
        self.add_coupling(self.server_receiver.output["ack_sent_to_sender"], self.output["ack_sent_to_sender"])
        self.add_coupling(self.server_sender.output["packet_forwarded"], self.output["packet_forwarded"])
        self.add_coupling(self.server_sender.output["ack_received_from_receiver"], self.output["ack_received_from_receiver"])
        self.add_coupling(self.receiver.output["processing_started"], self.output["processing_started"])
        self.add_coupling(self.receiver.output["ack_sent"], self.output["ack_sent"])
        self.add_coupling(self.server_sender.output["download_valve_change"], self.output["download_valve_change"])

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("INIT", 0)

    def deltext(self, e):
        self.hold_in("INIT", 0)

    def exit(self):
        pass

# Main function
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=10000.0)
    args = parser.parse_args()

    # Create system
    root = System("system", None, args.simulation_time)
    coord = Coordinator(root, clock=sim_clock)
    coord.initialize()

    # Read input from stdin
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        time_str = parts[0]
        event_type = parts[1]
        value = parts[2]
        timestamp = parse_time(time_str)

        # Schedule the event
        if event_type == "control":
            # Schedule control event
            def control_event():
                root.input["control"].add(int(value))
            sim_clock.schedule_event(timestamp, control_event)
        elif event_type == "request":
            # Schedule download valve event
            def download_event():
                root.input["download_valve"].add(int(value))
            sim_clock.schedule_event(timestamp, download_event)

    # Run simulation
    coord.simulate_time(args.simulation_time)

if __name__ == "__main__":
    main()