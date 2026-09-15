import argparse
import sys
import json
import logging
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Global simulation clock
sim_clock = SimulationClock(0)

# Helper to convert time strings to milliseconds
def parse_time(time_str):
    h, m, s, ms = map(int, time_str.split(':'))
    return h * 3600000 + m * 60000 + s * 1000 + ms

# Helper to log to stderr
def log_stderr(msg):
    print(msg, file=sys.stderr)

# Helper to log events to stdout as JSONL
def log_event(timestamp, model, event_type, val):
    event = {
        "timestamp_ms": timestamp,
        "model": model,
        "type": event_type,
        "val": val
    }
    print(json.dumps(event), file=sys.stdout, flush=True)

# Packet class to represent data packets
class Packet:
    def __init__(self, seq, bit):
        self.seq = seq
        self.bit = bit

# -------------------
# Atomic Models
# -------------------

class Sender(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(object, "input"))
        self.add_out_port(Port(object, "output"))
        self.add_out_port(Port(object, "ack"))
        self.add_out_port(Port(object, "timeout"))
        
        # State
        self.total_packets_to_send = 0
        self.packets_remaining = 0
        self.seq = 1
        self.bit = 0
        self.is_sending = False
        self.is_preparing = False
        self.timeout_timer = 0
        self.is_retry = False
        self.preparation_duration = 10000  # 10s in ms
        self.timeout_duration = 20000  # 20s in ms
        self.phase = "IDLE"
        self.sigma = 0

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.phase == "PREPARING":
            self.output["output"].add(Packet(self.seq, self.bit))
            self.output["ack"].add(Packet(self.seq, self.bit))
        elif self.phase == "SENDING":
            self.output["output"].add(Packet(self.seq, self.bit))
            self.output["ack"].add(Packet(self.seq, self.bit))
        elif self.phase == "TIMEOUT":
            self.output["timeout"].add(self.seq)

    def deltint(self):
        if self.phase == "IDLE":
            if self.packets_remaining > 0:
                self.phase = "PREPARING"
                self.sigma = self.preparation_duration
            else:
                self.sigma = 0
        elif self.phase == "PREPARING":
            self.phase = "SENDING"
            self.sigma = 0  # Immediate send
        elif self.phase == "SENDING":
            self.packets_remaining -= 1
            self.is_retry = False
            self.seq += 1
            self.bit = 1 - self.bit  # Flip bit
            if self.packets_remaining > 0:
                self.phase = "WAITING_ACK"
                self.sigma = self.timeout_duration
            else:
                self.phase = "IDLE"
                self.sigma = 0
        elif self.phase == "WAITING_ACK":
            self.phase = "IDLE"
            self.sigma = 0
        elif self.phase == "TIMEOUT":
            self.phase = "SENDING"
            self.is_retry = True
            self.sigma = 0

    def deltext(self, e):
        if self.phase == "IDLE":
            if self.input["input"].values:
                for val in self.input["input"].values:
                    if val["type"] == "control_cmd":
                        self.total_packets_to_send += val["val"]["added"]
                        self.packets_remaining = self.total_packets_to_send
                        if self.phase == "IDLE":
                            self.phase = "PREPARING"
                            self.sigma = self.preparation_duration
        elif self.phase == "WAITING_ACK":
            if self.input["input"].values:
                for val in self.input["input"].values:
                    if val["type"] == "ack_received":
                        self.phase = "SENDING"
                        self.sigma = 0
                    elif val["type"] == "timeout":
                        self.phase = "TIMEOUT"
                        self.sigma = 0

    def exit(self):
        pass

class ServerReceiver(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(object, "input"))
        self.add_out_port(Port(object, "output"))
        self.add_out_port(Port(object, "ack"))
        
        # State
        self.expected_bit = 0
        self.storage_queue = deque()
        self.processing_delay = 3000  # 3s in ms
        self.phase = "IDLE"
        self.sigma = 0

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.phase == "PROCESSING":
            if self.storage_queue:
                pkt = self.storage_queue[0]
                self.output["ack"].add(Packet(pkt.seq, pkt.bit))
                self.output["output"].add(pkt)

    def deltint(self):
        if self.phase == "IDLE":
            self.sigma = 0
        elif self.phase == "PROCESSING":
            self.phase = "IDLE"
            self.sigma = 0

    def deltext(self, e):
        if self.phase == "IDLE":
            if self.input["input"].values:
                for val in self.input["input"].values:
                    if val["type"] == "packet_received":
                        self.phase = "PROCESSING"
                        self.sigma = self.processing_delay
                        self.storage_queue.append(val["val"]["packet"])
                        log_event(sim_clock.time(), "server_receiver", "packet_received", val["val"])
                        # Log ACK immediately
                        log_event(sim_clock.time(), "server_receiver", "ack_sent_to_sender", {"bit": self.expected_bit})
                        # Check bit match
                        pkt = val["val"]["packet"]
                        if pkt.bit == self.expected_bit:
                            self.expected_bit = 1 - self.expected_bit
                        else:
                            # Duplicate - re-ACK previous bit
                            pass

    def exit(self):
        pass

class ServerSender(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(object, "input"))
        self.add_in_port(Port(object, "download_valve"))
        self.add_out_port(Port(object, "output"))
        self.add_out_port(Port(object, "ack"))
        self.add_out_port(Port(object, "stop"))

        # State
        self.storage_queue = deque()
        self.download_allowed = False
        self.is_sending = False
        self.phase = "IDLE"
        self.sigma = 0

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.phase == "SENDING":
            if self.storage_queue:
                pkt = self.storage_queue.popleft()
                self.output["output"].add(pkt)
                self.output["ack"].add(pkt)
                log_event(sim_clock.time(), "server_sender", "packet_forwarded", {"seq": pkt.seq, "bit": pkt.bit})

    def deltint(self):
        if self.phase == "IDLE":
            self.sigma = 0
        elif self.phase == "SENDING":
            self.phase = "IDLE"
            self.sigma = 0

    def deltext(self, e):
        if self.phase == "IDLE":
            if self.input["download_valve"].values:
                for val in self.input["download_valve"].values:
                    if val["type"] == "download_valve_change":
                        self.download_allowed = val["val"]["allowed"]
            if self.input["input"].values:
                for val in self.input["input"].values:
                    if val["type"] == "packet_received":
                        self.storage_queue.append(val["val"]["packet"])
            if self.download_allowed and self.storage_queue:
                self.phase = "SENDING"
                self.sigma = 0
        elif self.phase == "SENDING":
            if self.input["input"].values:
                for val in self.input["input"].values:
                    if val["type"] == "ack_received_from_receiver":
                        log_event(sim_clock.time(), "server_sender", "ack_received_from_receiver", {"bit": val["val"]["bit"]})
                        self.phase = "IDLE"
                        self.sigma = 0
                        if self.storage_queue and self.download_allowed:
                            self.phase = "SENDING"
                            self.sigma = 0

    def exit(self):
        pass

class Receiver(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(object, "input"))
        self.add_out_port(Port(object, "ack"))
        
        # State
        self.processing_delay = 10000  # 10s in ms
        self.phase = "IDLE"
        self.sigma = 0

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.phase == "PROCESSING":
            self.output["ack"].add(Packet(self.current_packet.seq, self.current_packet.bit))

    def deltint(self):
        if self.phase == "IDLE":
            self.sigma = 0
        elif self.phase == "PROCESSING":
            self.phase = "IDLE"
            self.sigma = 0

    def deltext(self, e):
        if self.phase == "IDLE":
            if self.input["input"].values:
                for val in self.input["input"].values:
                    if val["type"] == "packet_received":
                        self.current_packet = val["val"]["packet"]
                        self.phase = "PROCESSING"
                        self.sigma = self.processing_delay
                        log_event(sim_clock.time(), "receiver", "processing_started", {"seq": self.current_packet.seq, "duration": self.processing_delay})

    def exit(self):
        pass

class SubnetA1(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(object, "input"))
        self.add_out_port(Port(object, "output"))
        
        # State
        self.delay = 3000  # 3s in ms
        self.phase = "IDLE"
        self.sigma = 0

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.phase == "DELAY":
            self.output["output"].add(self.packet)

    def deltint(self):
        if self.phase == "IDLE":
            self.sigma = 0
        elif self.phase == "DELAY":
            self.phase = "IDLE"
            self.sigma = 0

    def deltext(self, e):
        if self.phase == "IDLE":
            if self.input["input"].values:
                for val in self.input["input"].values:
                    self.packet = val
                    self.phase = "DELAY"
                    self.sigma = self.delay

    def exit(self):
        pass

class SubnetA2(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(object, "input"))
        self.add_out_port(Port(object, "output"))
        
        # State
        self.delay = 3000  # 3s in ms
        self.phase = "IDLE"
        self.sigma = 0

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.phase == "DELAY":
            self.output["output"].add(self.packet)

    def deltint(self):
        if self.phase == "IDLE":
            self.sigma = 0
        elif self.phase == "DELAY":
            self.phase = "IDLE"
            self.sigma = 0

    def deltext(self, e):
        if self.phase == "IDLE":
            if self.input["input"].values:
                for val in self.input["input"].values:
                    self.packet = val
                    self.phase = "DELAY"
                    self.sigma = self.delay

    def exit(self):
        pass

class SubnetB1(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(object, "input"))
        self.add_out_port(Port(object, "output"))
        
        # State
        self.delay = 3000  # 3s in ms
        self.phase = "IDLE"
        self.sigma = 0

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.phase == "DELAY":
            self.output["output"].add(self.packet)

    def deltint(self):
        if self.phase == "IDLE":
            self.sigma = 0
        elif self.phase == "DELAY":
            self.phase = "IDLE"
            self.sigma = 0

    def deltext(self, e):
        if self.phase == "IDLE":
            if self.input["input"].values:
                for val in self.input["input"].values:
                    self.packet = val
                    self.phase = "DELAY"
                    self.sigma = self.delay

    def exit(self):
        pass

class SubnetB2(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(object, "input"))
        self.add_out_port(Port(object, "output"))
        
        # State
        self.delay = 3000  # 3s in ms
        self.phase = "IDLE"
        self.sigma = 0

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.phase == "DELAY":
            self.output["output"].add(self.packet)

    def deltint(self):
        if self.phase == "IDLE":
            self.sigma = 0
        elif self.phase == "DELAY":
            self.phase = "IDLE"
            self.sigma = 0

    def deltext(self, e):
        if self.phase == "IDLE":
            if self.input["input"].values:
                for val in self.input["input"].values:
                    self.packet = val
                    self.phase = "DELAY"
                    self.sigma = self.delay

    def exit(self):
        pass

# -------------------
# Coupled Model
# -------------------

class System(Coupled):
    def __init__(self, name, parent, simulate_time):
        super().__init__(name)
        self.parent = parent
        self.simulate_time = simulate_time

        # Instantiate components
        self.sender = Sender(name="sender", parent=self)
        self.server_receiver = ServerReceiver(name="server_receiver", parent=self)
        self.server_sender = ServerSender(name="server_sender", parent=self)
        self.receiver = Receiver(name="receiver", parent=self)
        self.subnet_a1 = SubnetA1(name="subnet_a1", parent=self)
        self.subnet_a2 = SubnetA2(name="subnet_a2", parent=self)
        self.subnet_b1 = SubnetB1(name="subnet_b1", parent=self)
        self.subnet_b2 = SubnetB2(name="subnet_b2", parent=self)

        self.add_component(self.sender)
        self.add_component(self.server_receiver)
        self.add_component(self.server_sender)
        self.add_component(self.receiver)
        self.add_component(self.subnet_a1)
        self.add_component(self.subnet_a2)
        self.add_component(self.subnet_b1)
        self.add_component(self.subnet_b2)

        # Define couplings
        # Sender to Subnet A1
        self.add_coupling(self.sender.output["output"], self.subnet_a1.input["input"])
        # Subnet A1 to Server Receiver
        self.add_coupling(self.subnet_a1.output["output"], self.server_receiver.input["input"])
        # Server Receiver to Subnet A2
        self.add_coupling(self.server_receiver.output["output"], self.subnet_a2.input["input"])
        # Subnet A2 to Sender
        self.add_coupling(self.subnet_a2.output["output"], self.sender.input["input"])
        # Server Receiver to Server Sender
        self.add_coupling(self.server_receiver.output["output"], self.server_sender.input["input"])
        # Server Sender to Subnet B1
        self.add_coupling(self.server_sender.output["output"], self.subnet_b1.input["input"])
        # Subnet B1 to Receiver
        self.add_coupling(self.subnet_b1.output["output"], self.receiver.input["input"])
        # Receiver to Subnet B2
        self.add_coupling(self.receiver.ack, self.subnet_b2.input["input"])
        # Subnet B2 to Server Sender
        self.add_coupling(self.subnet_b2.output["output"], self.server_sender.input["input"])
        # Server Sender to Server Receiver
        self.add_coupling(self.server_sender.ack, self.server_receiver.ack)
        # Sender to Server Sender (for download valve)
        self.add_coupling(self.sender.ack, self.server_sender.input["input"])
        # Download valve to Server Sender
        self.add_coupling(self.server_sender.download_valve, self.server_sender.download_valve)

    # No need for initialize, deltint, deltext, lambdaf in Coupled models

# -------------------
# Main Function
# -------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=10000.0)
    args = parser.parse_args()

    root = System(name="system", parent=None, simulate_time=args.simulation_time)
    coord = Coordinator(root, clock=sim_clock)
    coord.initialize()

    # Process stdin
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split(' ', 3)
        if len(parts) != 4:
            continue
        time_str, event_type, value_str = parts[0], parts[1], parts[2]
        timestamp = parse_time(time_str)
        value = int(value_str)

        # Schedule events based on time
        # We'll process them in order, but we need to simulate the time in the model
        # This is a simplified approach - better to use a proper event scheduler
        # but in this case, let's just assume we can inject events at time

        # For now, just add to input queue or trigger directly
        # Since we don't have event scheduling, simulate manually

    # Run simulation
    coord.simulate_time(args.simulation_time)
    sys.exit(0)

if __name__ == "__main__":
    main()