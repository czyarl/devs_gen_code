import argparse
import sys
import json
import logging
import collections
import random
import time

# xdevs imports
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Configure logging
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("xdevs_sim")

# --- Constants ---
TIME_SCALE = 1.0  # 1 simulation unit = 1 millisecond

# --- Helper Functions ---

def log_event(timestamp_ms, model, type_name, val):
    """Helper to print JSONL event to stdout."""
    event = {
        "timestamp_ms": timestamp_ms,
        "model": model,
        "type": type_name,
        "val": val
    }
    print(json.dumps(event), file=sys.stdout, flush=True)

def parse_time(time_str):
    """Parses HH:MM:SS or HH:MM:SS:mmm to milliseconds."""
    parts = time_str.split(':')
    if len(parts) == 3:
        h, m, s = map(int, parts)
        ms = 0
    elif len(parts) == 4:
        h, m, s, ms = map(int, parts)
    else:
        raise ValueError(f"Invalid time format: {time_str}")
    return (h * 3600 + m * 60 + s) * 1000 + ms

# --- Data Structures ---

class Packet:
    def __init__(self, seq, bit):
        self.seq = seq
        self.bit = bit

    def __repr__(self):
        return f"Packet(seq={self.seq}, bit={self.bit})"

class Ack:
    def __init__(self, bit):
        self.bit = bit

    def __repr__(self):
        return f"Ack(bit={self.bit})"

# --- Atomic Models ---

class Generator(Atomic):
    """
    Reads stdin and injects events into the system at specific simulation times.
    """
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.out_control = Port(int, "out_control")
        self.out_request = Port(int, "out_request")
        self.add_out_port(self.out_control)
        self.add_out_port(self.out_request)
        
        # State
        self.events = [] # List of (time_ms, type, value)
        self.phase = "IDLE"
        self.sigma = float('inf')
        
        # Read stdin immediately
        self._read_stdin()

    def _read_stdin(self):
        try:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) != 3:
                    logger.warning(f"Skipping malformed line: {line}")
                    continue
                
                t_str, type_name, val_str = parts
                t_ms = parse_time(t_str)
                
                if type_name == "control":
                    val = int(val_str)
                    self.events.append((t_ms, "control", val))
                elif type_name == "request":
                    val = int(val_str)
                    self.events.append((t_ms, "request", val))
                else:
                    logger.warning(f"Unknown command type: {type_name}")
            
            # Sort events by time
            self.events.sort(key=lambda x: x[0])
            logger.info(f"Generator loaded {len(self.events)} events.")
            
        except Exception as e:
            logger.error(f"Error reading stdin: {e}")

    def initialize(self):
        if self.events:
            first_time = self.events[0][0]
            self.hold_in("ACTIVE", first_time)
        else:
            self.hold_in("DONE", float('inf'))

    def lambdaf(self):
        if self.phase == "ACTIVE":
            # Process all events with the same timestamp as the head
            events_to_process = []
            
            target_time = self.events[0][0]
            
            while self.events and self.events[0][0] == target_time:
                events_to_process.append(self.events.pop(0))
            
            for _, type_name, val in events_to_process:
                if type_name == "control":
                    self.out_control.add(val)
                elif type_name == "request":
                    self.out_request.add(val)

    def deltint(self):
        if self.events:
            next_time = self.events[0][0]
            current_time = self.clock.get_time()
            delay = max(0.0, next_time - current_time)
            self.hold_in("ACTIVE", delay)
        else:
            self.hold_in("DONE", float('inf'))

    def deltext(self, e):
        # Generator is autonomous, ignores external input
        pass

    def exit(self):
        pass

class Sender(Atomic):
    """
    The Uploader.
    """
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.in_control = Port(int, "in_control")
        self.in_ack = Port(Ack, "in_ack")
        self.out_data = Port(Packet, "out_data")
        
        self.add_in_port(self.in_control)
        self.add_in_port(self.in_ack)
        self.add_out_port(self.out_data)
        
        # State
        self.total_packets_to_send = 0
        self.seq = 1
        self.bit = 0
        self.waiting_for_ack = False
        self.current_packet = None 
        
        self.phase = "IDLE"
        self.sigma = float('inf')

    def initialize(self):
        self.hold_in("IDLE", float('inf'))

    def lambdaf(self):
        if self.phase == "SENDING":
            if self.current_packet:
                is_retry = False # We log retries explicitly on timeout
                log_event(self.clock.get_time(), "sender", "packet_sent", 
                          {"seq": self.current_packet.seq, "bit": self.current_packet.bit, "is_retry": is_retry})
                self.out_data.add(self.current_packet)
        elif self.phase == "TIMEOUT":
            # Retransmit
            if self.current_packet:
                log_event(self.clock.get_time(), "sender", "packet_sent", 
                          {"seq": self.current_packet.seq, "bit": self.current_packet.bit, "is_retry": True})
                self.out_data.add(self.current_packet)

    def deltint(self):
        if self.phase == "PREPARING":
            # Finished preparing, send packet
            self.current_packet = Packet(self.seq, self.bit)
            self.waiting_for_ack = True
            self.hold_in("SENDING", 0) 
            
        elif self.phase == "SENDING":
            # Packet sent, wait for ACK
            self.hold_in("WAITING_ACK", 20000) # 20s timeout
            
        elif self.phase == "WAITING_ACK":
            # Timeout occurred
            log_event(self.clock.get_time(), "sender", "timeout", {"seq": self.seq})
            self.hold_in("TIMEOUT", 0) 
            
        elif self.phase == "TIMEOUT":
            # Just sent retry, go back to waiting
            self.hold_in("WAITING_ACK", 20000)

    def deltext(self, e):
        # Process Control Commands
        if self.in_control:
            for val in self.in_control.values:
                self.total_packets_to_send += val
                log_event(self.clock.get_time(), "sender", "control_cmd", 
                          {"added": val, "total_remaining": self.total_packets_to_send})
                
                if self.phase == "IDLE" and self.total_packets_to_send > 0:
                    log_event(self.clock.get_time(), "sender", "preparation_started", {"duration": 10000})
                    self.hold_in("PREPARING", 10000)
                elif self.phase == "DONE" and self.total_packets_to_send > 0:
                    log_event(self.clock.get_time(), "sender", "preparation_started", {"duration": 10000})
                    self.hold_in("PREPARING", 10000)

        # Process ACKs
        if self.in_ack:
            for ack in self.in_ack.values:
                log_event(self.clock.get_time(), "sender", "ack_received", {"bit": ack.bit})
                
                if self.waiting_for_ack and ack.bit == self.bit:
                    # Correct ACK
                    self.total_packets_to_send -= 1
                    self.bit = 1 - self.bit
                    self.seq += 1
                    self.waiting_for_ack = False
                    self.current_packet = None
                    
                    if self.total_packets_to_send > 0:
                        log_event(self.clock.get_time(), "sender", "preparation_started", {"duration": 10000})
                        self.hold_in("PREPARING", 10000)
                    else:
                        self.hold_in("DONE", float('inf'))
        
        # Preserve state if no transition occurred
        if self.phase == "WAITING_ACK":
            remaining = self.sigma - e
            self.hold_in("WAITING_ACK", remaining)
        elif self.phase == "PREPARING":
             remaining = self.sigma - e
             self.hold_in("PREPARING", remaining)

    def exit(self):
        pass

class ServerReceiver(Atomic):
    """
    Receives Data from Sender, processes (3s), sends ACK.
    """
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.in_data = Port(Packet, "in_data")
        self.out_ack = Port(Ack, "out_ack")
        self.out_storage = Port(Packet, "out_storage")
        
        self.add_in_port(self.in_data)
        self.add_out_port(self.out_ack)
        self.add_out_port(self.out_storage)
        
        # State
        self.expected_bit = 0
        self.processing_packet = None
        self.phase = "IDLE"
        self.sigma = float('inf')

    def initialize(self):
        self.hold_in("IDLE", float('inf'))

    def lambdaf(self):
        if self.phase == "SEND_ACK":
            if self.processing_packet:
                bit_to_ack = self.processing_packet.bit
                self.out_ack.add(Ack(bit_to_ack))
                log_event(self.clock.get_time(), "server_receiver", "ack_sent_to_sender", {"bit": bit_to_ack})
                
                if self.processing_packet.bit == self.expected_bit:
                    self.out_storage.add(self.processing_packet)
                    self.expected_bit = 1 - self.expected_bit

    def deltint(self):
        if self.phase == "PROCESSING":
            self.hold_in("SEND_ACK", 0)
        elif self.phase == "SEND_ACK":
            self.processing_packet = None
            self.hold_in("IDLE", float('inf'))

    def deltext(self, e):
        if self.in_data:
            for p in self.in_data.values:
                log_event(self.clock.get_time(), "server_receiver", "packet_received", {"seq": p.seq, "bit": p.bit})
                self.processing_packet = p
                self.hold_in("PROCESSING", 3000)
        
        if self.phase == "IDLE" and not self.in_data:
            self.hold_in("IDLE", float('inf'))
        elif self.phase == "PROCESSING" and not self.in_data:
            remaining = self.sigma - e
            self.hold_in("PROCESSING", remaining)
            
    def exit(self):
        pass

class ServerSender(Atomic):
    """
    Egress Logic.
    """
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.in_storage = Port(Packet, "in_storage")
        self.in_request = Port(int, "in_request")
        self.in_ack = Port(Ack, "in_ack")
        self.out_data = Port(Packet, "out_data")
        
        self.add_in_port(self.in_storage)
        self.add_in_port(self.in_request)
        self.add_in_port(self.in_ack)
        self.add_out_port(self.out_data)
        
        # State
        self.queue = collections.deque()
        self.download_allowed = False
        self.bit = 0
        self.waiting_for_ack = False
        self.current_packet = None
        
        self.phase = "IDLE"
        self.sigma = float('inf')

    def initialize(self):
        self.hold_in("IDLE", float('inf'))

    def lambdaf(self):
        if self.phase == "SENDING":
            if self.current_packet:
                log_event(self.clock.get_time(), "server_sender", "packet_forwarded", 
                          {"seq": self.current_packet.seq, "bit": self.current_packet.bit})
                self.out_data.add(self.current_packet)

    def deltint(self):
        if self.phase == "SENDING":
            self.hold_in("WAITING_ACK", 20000)
            
    def deltext(self, e):
        state_changed = False
        
        if self.in_storage:
            for p in self.in_storage.values:
                self.queue.append(p)
        
        if self.in_request:
            for val in self.in_request.values:
                new_allowed = (val == 1)
                if self.download_allowed != new_allowed:
                    self.download_allowed = new_allowed
                    log_event(self.clock.get_time(), "server_sender", "download_valve_change", {"allowed": self.download_allowed})
        
        if self.in_ack:
            for ack in self.in_ack.values:
                log_event(self.clock.get_time(), "server_sender", "ack_received_from_receiver", {"bit": ack.bit})
                if self.waiting_for_ack and ack.bit == self.bit:
                    self.waiting_for_ack = False
                    self.current_packet = None
                    self.bit = 1 - self.bit
                    state_changed = True

        if not self.waiting_for_ack:
            if self.queue and self.download_allowed:
                self.current_packet = self.queue.popleft()
                self.waiting_for_ack = True
                self.hold_in("SENDING", 0)
                state_changed = True
            else:
                self.hold_in("IDLE", float('inf'))
                state_changed = True
        
        if self.waiting_for_ack and not state_changed:
            remaining = self.sigma - e
            self.hold_in("WAITING_ACK", remaining)
            
        if self.phase == "IDLE" and not state_changed:
             self.hold_in("IDLE", float('inf'))

    def exit(self):
        pass

class Receiver(Atomic):
    """
    Receives Data from Server, processes (10s), sends ACK.
    """
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.in_data = Port(Packet, "in_data")
        self.out_ack = Port(Ack, "out_ack")
        
        self.add_in_port(self.in_data)
        self.add_out_port(self.out_ack)
        
        # State
        self.processing_packet = None
        self.phase = "IDLE"
        self.sigma = float('inf')

    def initialize(self):
        self.hold_in("IDLE", float('inf'))

    def lambdaf(self):
        if self.phase == "SEND_ACK":
            if self.processing_packet:
                log_event(self.clock.get_time(), "receiver", "ack_sent", {"bit": self.processing_packet.bit})
                self.out_ack.add(Ack(self.processing_packet.bit))

    def deltint(self):
        if self.phase == "PROCESSING":
            self.hold_in("SEND_ACK", 0)
        elif self.phase == "SEND_ACK":
            self.processing_packet = None
            self.hold_in("IDLE", float('inf'))

    def deltext(self, e):
        if self.in_data:
            for p in self.in_data.values:
                self.processing_packet = p
                log_event(self.clock.get_time(), "receiver", "processing_started", 
                          {"seq": p.seq, "duration": 10000})
                self.hold_in("PROCESSING", 10000)
        
        if self.phase == "IDLE" and not self.in_data:
            self.hold_in("IDLE", float('inf'))
        elif self.phase == "PROCESSING" and not self.in_data:
            remaining = self.sigma - e
            self.hold_in("PROCESSING", remaining)

    def exit(self):
        pass

class Subnet(Atomic):
    """
    Reliable, FIFO, fixed delay channel.
    """
    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        
        self.in_data = Port(object, "in_data")
        self.out_data = Port(object, "out_data")
        
        self.add_in_port(self.in_data)
        self.add_out_port(self.out_data)
        
        self.queue = collections.deque() 
        self.phase = "IDLE"
        self.sigma = float('inf')

    def initialize(self):
        self.hold_in("IDLE", float('inf'))

    def lambdaf(self):
        if self.phase == "OUTPUT":
            if self.queue:
                payload, _ = self.queue.popleft()
                self.out_data.add(payload)

    def deltint(self):
        if self.phase == "OUTPUT":
            if self.queue:
                next_delivery_time = self.queue[0][1]
                current_time = self.clock.get_time()
                delay = max(0.0, next_delivery_time - current_time)
                self.hold_in("OUTPUT", delay)
            else:
                self.hold_in("IDLE", float('inf'))

    def deltext(self, e):
        if self.in_data:
            current_time = self.clock.get_time()
            for val in self.in_data.values:
                delivery_time = current_time + self.delay
                self.queue.append((val, delivery_time))
        
        if self.queue:
            next_delivery_time = self.queue[0][1]
            current_time = self.clock.get_time()
            delay = max(0.0, next_delivery_time - current_time)
            self.hold_in("OUTPUT", delay)
        else:
            self.hold_in("IDLE", float('inf'))

    def exit(self):
        pass

# --- Coupled Models ---

class Server(Coupled):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        self.server_receiver = ServerReceiver("server_receiver", self)
        self.server_sender = ServerSender("server_sender", self)
        
        self.add_component(self.server_receiver)
        self.add_component(self.server_sender)
        
        self.in_data = Port(Packet, "in_data")
        self.out_ack = Port(Ack, "out_ack")
        self.out_data = Port(Packet, "out_data")
        self.in_ack = Port(Ack, "in_ack")
        self.in_request = Port(int, "in_request")
        
        self.add_in_port(self.in_data)
        self.add_out_port(self.out_ack)
        self.add_out_port(self.out_data)
        self.add_in_port(self.in_ack)
        self.add_in_port(self.in_request)
        
        self.add_coupling(self.in_data, self.server_receiver.in_data)
        self.add_coupling(self.server_receiver.out_ack, self.out_ack)
        self.add_coupling(self.server_receiver.out_storage, self.server_sender.in_storage)
        
        self.add_coupling(self.server_sender.out_data, self.out_data)
        self.add_coupling(self.in_ack, self.server_sender.in_ack)
        self.add_coupling(self.in_request, self.server_sender.in_request)

class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        self.generator = Generator("generator", self)
        self.sender = Sender("sender", self)
        self.server = Server("server", self)
        self.receiver = Receiver("receiver", self)
        
        self.sub_a1 = Subnet("sub_a1", self, 3000)
        self.sub_a2 = Subnet("sub_a2", self, 3000)
        self.sub_b1 = Subnet("sub_b1", self, 3000)
        self.sub_b2 = Subnet("sub_b2", self, 3000)
        
        self.add_component(self.generator)
        self.add_component(self.sender)
        self.add_component(self.server)
        self.add_component(self.receiver)
        self.add_component(self.sub_a1)
        self.add_component(self.sub_a2)
        self.add_component(self.sub_b1)
        self.add_component(self.sub_b2)
        
        self.add_coupling(self.generator.out_control, self.sender.in_control)
        self.add_coupling(self.generator.out_request, self.server.in_request)
        
        self.add_coupling(self.sender.out_data, self.sub_a1.in_data)
        self.add_coupling(self.sub_a1.out_data, self.server.in_data)
        
        self.add_coupling(self.server.out_ack, self.sub_a2.in_data)
        self.add_coupling(self.sub_a2.out_data, self.sender.in_ack)
        
        self.add_coupling(self.server.out_data, self.sub_b1.in_data)
        self.add_coupling(self.sub_b1.out_data, self.receiver.in_data)
        
        self.add_coupling(self.receiver.out_ack, self.sub_b2.in_data)
        self.add_coupling(self.sub_b2.out_data, self.server.in_ack)

def main():
    parser = argparse.ArgumentParser(description="Dropbox-like Synchronization Simulation")
    parser.add_argument("--simulation_time", type=float, default=10000000.0, help="Simulation duration in ms")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    
    args = parser.parse_args()
    
    random.seed(args.seed)
    
    root = System(name="system", parent=None)
    
    coord = Coordinator(root, clock=SimulationClock(0))
    
    coord.initialize()
    
    coord.simulate_time(args.simulation_time)

if __name__ == "__main__":
    main()