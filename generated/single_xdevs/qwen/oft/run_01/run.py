import argparse
import sys
import json
import logging
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)

class TimeParser:
    @staticmethod
    def parse_time(time_str):
        """Parse time string in format HH:MM:SS:mmm into milliseconds."""
        h, m, s, ms = map(int, time_str.split(':'))
        return (h * 3600 + m * 60 + s) * 1000 + ms

class EventLogger:
    def __init__(self):
        self.events = []

    def log(self, timestamp_ms, model, event_type, val):
        event = {
            "timestamp_ms": timestamp_ms,
            "model": model,
            "type": event_type,
            "val": val
        }
        self.events.append(event)
        print(json.dumps(event), file=sys.stdout, flush=True)

# Constants
ABP_TIMEOUT = 20000  # 20 seconds
PREPARE_DURATION = 10000  # 10 seconds
SERVER_RECEIVE_DELAY = 3000  # 3 seconds
RECEIVER_PROCESS_DELAY = 10000  # 10 seconds

class Sender(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(int, "control"))
        self.add_out_port(Port(dict, "to_subnet_a1"))
        self.add_in_port(Port(dict, "ack_from_subnet_a2"))
        self.add_in_port(Port(int, "reset"))
        
        # State
        self.packets_remaining = 0
        self.expected_bit = 0
        self.next_seq = 1
        self.is_preparing = False
        self.is_sending = False
        self.retry_count = 0
        self.timeout_timer = None
        self.packet_sent = None

        self.hold_in("IDLE", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        if self.phase == "PREPARE":
            self.hold_in("SENDING", 0)
        elif self.phase == "WAIT_ACK":
            self.is_sending = False
            self.hold_in("IDLE", 0)
        elif self.phase == "SENDING":
            # Send the packet
            packet = {"seq": self.next_seq, "bit": self.expected_bit}
            self.output["to_subnet_a1"].add(packet)
            self.packet_sent = packet
            self.is_sending = True
            self.hold_in("WAIT_ACK", ABP_TIMEOUT)
        elif self.phase == "IDLE":
            if self.packets_remaining > 0:
                self.hold_in("PREPARE", PREPARE_DURATION)
            else:
                self.hold_in("IDLE", 0)

    def deltext(self, e):
        if self.phase == "IDLE":
            if "control" in self.input:
                for value in self.input["control"].values:
                    self.packets_remaining += value
                    self.log_event("control_cmd", {"added": value, "total_remaining": self.packets_remaining})
                if self.packets_remaining > 0:
                    self.hold_in("PREPARE", PREPARE_DURATION)
                else:
                    self.hold_in("IDLE", 0)
            elif "reset" in self.input:
                self.packets_remaining = 0
                self.hold_in("IDLE", 0)
        elif self.phase == "PREPARE":
            if "control" in self.input:
                for value in self.input["control"].values:
                    self.packets_remaining += value
                    self.log_event("control_cmd", {"added": value, "total_remaining": self.packets_remaining})
            elif "reset" in self.input:
                self.packets_remaining = 0
                self.hold_in("IDLE", 0)
        elif self.phase == "SENDING":
            if "control" in self.input:
                for value in self.input["control"].values:
                    self.packets_remaining += value
                    self.log_event("control_cmd", {"added": value, "total_remaining": self.packets_remaining})
        elif self.phase == "WAIT_ACK":
            if "ack_from_subnet_a2" in self.input:
                ack = self.input["ack_from_subnet_a2"].values[0]
                if ack["bit"] == self.expected_bit:
                    self.log_event("ack_received", {"bit": ack["bit"]})
                    self.packets_remaining -= 1
                    self.expected_bit = 1 - self.expected_bit
                    self.next_seq += 1
                    self.retry_count = 0
                    if self.packets_remaining <= 0:
                        self.hold_in("IDLE", 0)
                    else:
                        self.hold_in("SENDING", 0)
                else:
                    self.log_event("timeout", {"seq": self.packet_sent["seq"]})
                    self.retry_count += 1
                    self.hold_in("SENDING", 0)
            elif "control" in self.input:
                for value in self.input["control"].values:
                    self.packets_remaining += value
                    self.log_event("control_cmd", {"added": value, "total_remaining": self.packets_remaining})
            elif "reset" in self.input:
                self.packets_remaining = 0
                self.hold_in("IDLE", 0)

    def exit(self):
        pass

    def log_event(self, event_type, val):
        timestamp = self.get_time()
        logger.log(timestamp, "sender", event_type, val)

class ServerReceiver(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "from_subnet_a1"))
        self.add_out_port(Port(dict, "to_subnet_a2"))
        self.add_out_port(Port(dict, "to_server_storage"))

        # State
        self.expected_bit = 0
        self.storage_queue = deque()
        self.processing_packet = None
        self.processing_timer = None

        self.hold_in("IDLE", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        if self.phase == "PROCESSING":
            # Send ACK back to sender
            ack = {"bit": self.expected_bit}
            self.output["to_subnet_a2"].add(ack)
            self.log_event("ack_sent_to_sender", {"bit": self.expected_bit})
            # Store packet in queue
            self.storage_queue.append(self.processing_packet)
            self.log_event("packet_received", {"seq": self.processing_packet["seq"], "bit": self.processing_packet["bit"]})
            # Flip expected bit
            self.expected_bit = 1 - self.expected_bit
            self.hold_in("IDLE", 0)
        elif self.phase == "IDLE":
            self.hold_in("IDLE", 0)

    def deltext(self, e):
        if "from_subnet_a1" in self.input:
            packet = self.input["from_subnet_a1"].values[0]
            self.processing_packet = packet
            self.log_event("packet_received", {"seq": packet["seq"], "bit": packet["bit"]})
            self.hold_in("PROCESSING", SERVER_RECEIVE_DELAY)

    def exit(self):
        pass

    def log_event(self, event_type, val):
        timestamp = self.get_time()
        logger.log(timestamp, "server_receiver", event_type, val)

class ServerSender(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "from_server_storage"))
        self.add_in_port(Port(int, "download_allowed"))
        self.add_out_port(Port(dict, "to_subnet_b1"))
        self.add_in_port(Port(dict, "ack_from_subnet_b2"))
        self.add_out_port(Port(dict, "to_server_storage"))

        # State
        self.storage_queue = deque()
        self.download_allowed = False
        self.is_sending = False
        self.current_packet = None
        self.waiting_for_ack = False
        self.retry_count = 0

        self.hold_in("IDLE", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        if self.phase == "WAIT_ACK":
            self.waiting_for_ack = False
            self.is_sending = False
            self.hold_in("IDLE", 0)
        elif self.phase == "SENDING":
            if self.storage_queue and self.download_allowed:
                # Pop packet from queue
                packet = self.storage_queue.popleft()
                self.current_packet = packet
                self.output["to_subnet_b1"].add(packet)
                self.log_event("packet_forwarded", {"seq": packet["seq"], "bit": packet["bit"]})
                self.hold_in("WAIT_ACK", ABP_TIMEOUT)
            else:
                self.hold_in("IDLE", 0)
        elif self.phase == "IDLE":
            if self.storage_queue and self.download_allowed:
                self.hold_in("SENDING", 0)
            else:
                self.hold_in("IDLE", 0)

    def deltext(self, e):
        if "from_server_storage" in self.input:
            for packet in self.input["from_server_storage"].values:
                self.storage_queue.append(packet)
                self.log_event("packet_forwarded", {"seq": packet["seq"], "bit": packet["bit"]})
                if self.download_allowed and not self.is_sending and not self.waiting_for_ack:
                    self.hold_in("SENDING", 0)
        elif "download_allowed" in self.input:
            for value in self.input["download_allowed"].values:
                self.download_allowed = bool(value)
                self.log_event("download_valve_change", {"allowed": self.download_allowed})
                if self.download_allowed and self.storage_queue and not self.is_sending and not self.waiting_for_ack:
                    self.hold_in("SENDING", 0)
                elif not self.download_allowed and self.is_sending:
                    self.hold_in("IDLE", 0)
        elif "ack_from_subnet_b2" in self.input:
            ack = self.input["ack_from_subnet_b2"].values[0]
            self.log_event("ack_received_from_receiver", {"bit": ack["bit"]})
            self.waiting_for_ack = False
            self.is_sending = False
            if self.storage_queue and self.download_allowed:
                self.hold_in("SENDING", 0)
            else:
                self.hold_in("IDLE", 0)

    def exit(self):
        pass

    def log_event(self, event_type, val):
        timestamp = self.get_time()
        logger.log(timestamp, "server_sender", event_type, val)

class Receiver(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "from_subnet_b1"))
        self.add_out_port(Port(dict, "to_subnet_b2"))

        # State
        self.processing_packet = None
        self.processing_timer = None

        self.hold_in("IDLE", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        if self.phase == "PROCESSING":
            # Send ACK back to server
            ack = {"bit": self.processing_packet["bit"]}
            self.output["to_subnet_b2"].add(ack)
            self.log_event("ack_sent", {"bit": self.processing_packet["bit"]})
            self.hold_in("IDLE", 0)
        elif self.phase == "IDLE":
            self.hold_in("IDLE", 0)

    def deltext(self, e):
        if "from_subnet_b1" in self.input:
            packet = self.input["from_subnet_b1"].values[0]
            self.processing_packet = packet
            self.log_event("processing_started", {"seq": packet["seq"], "duration": RECEIVER_PROCESS_DELAY})
            self.hold_in("PROCESSING", RECEIVER_PROCESS_DELAY)

    def exit(self):
        pass

    def log_event(self, event_type, val):
        timestamp = self.get_time()
        logger.log(timestamp, "receiver", event_type, val)

class SubnetA1(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "from_sender"))
        self.add_out_port(Port(dict, "to_server_receiver"))

        self.hold_in("IDLE", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("IDLE", 0)

    def deltext(self, e):
        if "from_sender" in self.input:
            for packet in self.input["from_sender"].values:
                self.output["to_server_receiver"].add(packet)
                self.hold_in("IDLE", 3000)  # 3s delay

    def exit(self):
        pass

class SubnetA2(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "from_server_receiver"))
        self.add_out_port(Port(dict, "to_sender"))

        self.hold_in("IDLE", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("IDLE", 0)

    def deltext(self, e):
        if "from_server_receiver" in self.input:
            for ack in self.input["from_server_receiver"].values:
                self.output["to_sender"].add(ack)
                self.hold_in("IDLE", 3000)  # 3s delay

    def exit(self):
        pass

class SubnetB1(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "from_server_sender"))
        self.add_out_port(Port(dict, "to_receiver"))

        self.hold_in("IDLE", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("IDLE", 0)

    def deltext(self, e):
        if "from_server_sender" in self.input:
            for packet in self.input["from_server_sender"].values:
                self.output["to_receiver"].add(packet)
                self.hold_in("IDLE", 3000)  # 3s delay

    def exit(self):
        pass

class SubnetB2(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "from_receiver"))
        self.add_out_port(Port(dict, "to_server_sender"))

        self.hold_in("IDLE", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("IDLE", 0)

    def deltext(self, e):
        if "from_receiver" in self.input:
            for ack in self.input["from_receiver"].values:
                self.output["to_server_sender"].add(ack)
                self.hold_in("IDLE", 3000)  # 3s delay

    def exit(self):
        pass

class System(Coupled):
    def __init__(self, name, parent, simulate_time):
        super().__init__(name)
        self.parent = parent
        self.simulate_time = simulate_time
        
        # Create components
        self.sender = Sender("sender", self)
        self.server_receiver = ServerReceiver("server_receiver", self)
        self.server_sender = ServerSender("server_sender", self)
        self.receiver = Receiver("receiver", self)
        self.subnet_a1 = SubnetA1("subnet_a1", self)
        self.subnet_a2 = SubnetA2("subnet_a2", self)
        self.subnet_b1 = SubnetB1("subnet_b1", self)
        self.subnet_b2 = SubnetB2("subnet_b2", self)
        
        # Add components to system
        self.add_component(self.sender)
        self.add_component(self.server_receiver)
        self.add_component(self.server_sender)
        self.add_component(self.receiver)
        self.add_component(self.subnet_a1)
        self.add_component(self.subnet_a2)
        self.add_component(self.subnet_b1)
        self.add_component(self.subnet_b2)
        
        # Add couplings
        # Sender to Subnet A1
        self.add_coupling(self.sender.output["to_subnet_a1"], self.subnet_a1.input["from_sender"])
        # Subnet A1 to Server Receiver
        self.add_coupling(self.subnet_a1.output["to_server_receiver"], self.server_receiver.input["from_subnet_a1"])
        # Server Receiver to Subnet A2
        self.add_coupling(self.server_receiver.output["to_subnet_a2"], self.subnet_a2.input["from_server_receiver"])
        # Subnet A2 to Sender
        self.add_coupling(self.subnet_a2.output["to_sender"], self.sender.input["ack_from_subnet_a2"])
        
        # Server Receiver to Server Storage
        self.add_coupling(self.server_receiver.output["to_server_storage"], self.server_sender.input["from_server_storage"])
        
        # Server Sender to Subnet B1
        self.add_coupling(self.server_sender.output["to_subnet_b1"], self.subnet_b1.input["from_server_sender"])
        # Subnet B1 to Receiver
        self.add_coupling(self.subnet_b1.output["to_receiver"], self.receiver.input["from_subnet_b1"])
        # Receiver to Subnet B2
        self.add_coupling(self.receiver.output["to_subnet_b2"], self.subnet_b2.input["from_receiver"])
        # Subnet B2 to Server Sender
        self.add_coupling(self.subnet_b2.output["to_server_sender"], self.server_sender.input["ack_from_subnet_b2"])
        
        # Download permission input
        self.add_coupling(self.server_sender.input["download_allowed"], self.server_sender.output["to_server_storage"])
        
        # Control input to Sender
        self.add_coupling(self.sender.input["control"], self.sender.output["to_subnet_a1"])

def main():
    global logger
    logger = EventLogger()
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=10000.0)
    args = parser.parse_args()

    root = System(name="system", parent=None, simulate_time=args.simulation_time)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    
    # Read input from stdin
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 3:
            continue
        time_str, cmd_type, value_str = parts
        timestamp = TimeParser.parse_time(time_str)
        
        if cmd_type == "control":
            value = int(value_str)
            coord.schedule_input("sender", "control", value, timestamp)
        elif cmd_type == "request":
            value = int(value_str)
            coord.schedule_input("server_sender", "download_allowed", value, timestamp)
    
    # Run simulation
    coord.simulate_time(args.simulation_time)

if __name__ == "__main__":
    main()