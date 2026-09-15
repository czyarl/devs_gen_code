<python_code>
import argparse
import sys
import json
import logging
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Configure logging to stderr
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Constants ---
TIME_PREPARATION = 10.0
TIMEOUT_SENDER = 20.0
DELAY_SERVER_PROCESSING = 3.0
DELAY_RECEIVER_PROCESSING = 10.0
DELAY_SUBNET = 3.0

# --- Helper Functions ---

def log_event(timestamp_ms, model, event_type, val):
    print(json.dumps({
        "timestamp_ms": timestamp_ms,
        "model": model,
        "type": event_type,
        "val": val
    }), file=sys.stdout, flush=True)

def parse_time_str(time_str):
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

# --- Atomic Models ---

class Sender(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.add_in_port(Port(int, "control"))
        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "data_out"))
        
        # State
        self.packets_remaining = 0
        self.current_seq = 1
        self.current_bit = 0
        self.phase = "IDLE"
        self.sigma = float('inf')
        self.is_retry = False
        self.last_sent_packet = None

    def initialize(self):
        self.hold_in("IDLE", float('inf'))

    def lambdaf(self):
        if self.phase == "SEND_DATA":
            pkt = self.last_sent_packet
            self.output["data_out"].add(pkt)
            log_event(self.clock.get_time() * 1000, "sender", "packet_sent", 
                      {"seq": pkt['seq'], "bit": pkt['bit'], "is_retry": self.is_retry})

    def deltint(self):
        time = self.clock.get_time()
        
        if self.phase == "PREPARE":
            self.is_retry = False
            self.last_sent_packet = {"seq": self.current_seq, "bit": self.current_bit}
            self.phase = "SEND_DATA"
            self.sigma = 0
            
        elif self.phase == "SEND_DATA":
            self.phase = "WAIT_ACK"
            self.sigma = TIMEOUT_SENDER
            
        elif self.phase == "WAIT_ACK":
            log_event(time * 1000, "sender", "timeout", {"seq": self.current_seq})
            self.is_retry = True
            self.phase = "SEND_DATA"
            self.sigma = 0

        self.hold_in(self.phase, self.sigma)

    def deltext(self, e):
        time = self.clock.get_time()
        self.sigma -= e
        
        for val in self.input["control"].values:
            added = val
            self.packets_remaining += added
            log_event(time * 1000, "sender", "control_cmd", 
                      {"added": added, "total_remaining": self.packets_remaining})
            
            if self.phase == "IDLE" and self.packets_remaining > 0:
                log_event(time * 1000, "sender", "preparation_started", {"duration": int(TIME_PREPARATION * 1000)})
                self.phase = "PREPARE"
                self.sigma = TIME_PREPARATION

        for val in self.input["ack_in"].values:
            ack_bit = val['bit']
            log_event(time * 1000, "sender", "ack_received", {"bit": ack_bit})
            
            if self.phase == "WAIT_ACK":
                if ack_bit == self.current_bit:
                    self.current_bit = 1 - self.current_bit
                    self.current_seq += 1
                    self.packets_remaining -= 1
                    
                    if self.packets_remaining > 0:
                        log_event(time * 1000, "sender", "preparation_started", {"duration": int(TIME_PREPARATION * 1000)})
                        self.phase = "PREPARE"
                        self.sigma = TIME_PREPARATION
                    else:
                        self.phase = "IDLE"
                        self.sigma = float('inf')

        self.hold_in(self.phase, self.sigma)

    def exit(self):
        pass

class ServerReceiver(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "ack_out"))
        self.add_out_port(Port(dict, "storage_out"))
        
        self.expected_bit = 0
        self.phase = "IDLE"
        self.sigma = float('inf')
        self.current_packet = None

    def initialize(self):
        self.hold_in("IDLE", float('inf'))

    def lambdaf(self):
        if self.phase == "SEND_ACK":
            self.output["ack_out"].add({"bit": self.current_packet['bit']})
            log_event(self.clock.get_time() * 1000, "server_receiver", "ack_sent_to_sender", {"bit": self.current_packet['bit']})
        elif self.phase == "PUSH_STORAGE":
            self.output["storage_out"].add(self.current_packet)

    def deltint(self):
        if self.phase == "PROCESSING":
            self.phase = "SEND_ACK"
            self.sigma = 0
        elif self.phase == "SEND_ACK":
            self.phase = "PUSH_STORAGE"
            self.sigma = 0
        elif self.phase == "PUSH_STORAGE":
            self.phase = "IDLE"
            self.sigma = float('inf')
        self.hold_in(self.phase, self.sigma)

    def deltext(self, e):
        self.sigma -= e
        time = self.clock.get_time()
        
        for val in self.input["data_in"].values:
            pkt = val
            log_event(time * 1000, "server_receiver", "packet_received", {"seq": pkt['seq'], "bit": pkt['bit']})
            self.current_packet = pkt
            
            if pkt['bit'] == self.expected_bit:
                self.phase = "PROCESSING"
                self.sigma = DELAY_SERVER_PROCESSING
            else:
                self.phase = "SEND_ACK"
                self.sigma = 0

        self.hold_in(self.phase, self.sigma)

    def exit(self):
        pass

class ServerSender(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        self.add_in_port(Port(int, "request"))
        self.add_in_port(Port(dict, "storage_in"))
        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "data_out"))
        
        self.download_allowed = False
        self.storage = deque()
        self.current_bit = 0
        self.phase = "IDLE"
        self.sigma = float('inf')
        self.last_sent_packet = None

    def initialize(self):
        self.hold_in("IDLE", float('inf'))

    def lambdaf(self):
        if self.phase == "SEND_DATA":
            self.output["data_out"].add(self.last_sent_packet)
            log_event(self.clock.get_time() * 1000, "server_sender", "packet_forwarded", 
                      {"seq": self.last_sent_packet['seq'], "bit": self.last_sent_packet['bit']})

    def deltint(self):
        if self.phase == "SEND_DATA":
            self.phase = "WAIT_ACK"
            self.sigma = TIMEOUT_SENDER 
        elif self.phase == "WAIT_ACK":
            self.phase = "SEND_DATA"
            self.sigma = 0
        self.hold_in(self.phase, self.sigma)

    def deltext(self, e):
        self.sigma -= e
        time = self.clock.get_time()
        
        for val in self.input["request"].values:
            new_val = bool(val)
            if self.download_allowed != new_val:
                self.download_allowed = new_val
                log_event(time * 1000, "server_sender", "download_valve_change", {"allowed": self.download_allowed})
        
        for val in self.input["storage_in"].values:
            self.storage.append(val)
            if self.phase == "IDLE" and self.download_allowed:
                self._start_next_packet()
                
        for val in self.input["ack_in"].values:
            ack_bit = val['bit']
            log_event(time * 1000, "server_sender", "ack_received_from_receiver", {"bit": ack_bit})
            
            if self.phase == "WAIT_ACK":
                if ack_bit == self.current_bit:
                    self.current_bit = 1 - self.current_bit
                    if self.storage and self.download_allowed:
                        self._start_next_packet()
                    else:
                        self.phase = "IDLE"
                        self.sigma = float('inf')

        self.hold_in(self.phase, self.sigma)

    def _start_next_packet(self):
        if self.storage:
            pkt = self.storage.popleft()
            self.last_sent_packet = pkt
            self.current_bit = pkt['bit']
            self.phase = "SEND_DATA"
            self.sigma = 0

    def exit(self):
        pass

class Receiver(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "ack_out"))
        
        self.expected_bit = 0
        self.phase = "IDLE"
        self.sigma = float('inf')
        self.current_packet = None

    def initialize(self):
        self.hold_in("IDLE", float('inf'))

    def lambdaf(self):
        if self.phase == "SEND_ACK":
            self.output["ack_out"].add({"bit": self.current_packet['bit']})
            log_event(self.clock.get_time() * 1000, "receiver", "ack_sent", {"bit": self.current_packet['bit']})

    def deltint(self):
        if self.phase == "PROCESSING":
            self.phase = "SEND_ACK"
            self.sigma = 0
        elif self.phase == "SEND_ACK":
            self.phase = "IDLE"
            self.sigma = float('inf')
        self.hold_in(self.phase, self.sigma)

    def deltext(self, e):
        self.sigma -= e
        time = self.clock.get_time()
        
        for val in self.input["data_in"].values:
            pkt = val
            if pkt['bit'] == self.expected_bit:
                self.current_packet = pkt
                log_event(time * 1000, "receiver", "processing_started", 
                          {"seq": pkt['seq'], "duration": int(DELAY_RECEIVER_PROCESSING * 1000)})
                self.phase = "PROCESSING"
                self.sigma = DELAY_RECEIVER_PROCESSING
                self.expected_bit = 1 - self.expected_bit
            else:
                self.output["ack_out"].add({"bit": self.expected_bit})
                log_event(time * 1000, "receiver", "ack_sent", {"bit": self.expected_bit})
                self.phase = "SEND_ACK"
                self.sigma = 0
                self.current_packet = {"bit": self.expected_bit}

        self.hold_in(self.phase, self.sigma)

    def exit(self):
        pass

class Subnet(Atomic):
    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        self.add_in_port(Port(dict, "in"))
        self.add_out_port(Port(dict, "out"))
        self.queue = []
        self.phase = "IDLE"
        self.sigma = float('inf')

    def initialize(self):
        self.queue = [] 
        self.hold_in("IDLE", float('inf'))

    def lambdaf(self):
        if self.queue:
            _, data = self.queue[0]
            self.output["out"].add(data)

    def deltint(self):
        current_time = self.clock.get_time()
        if self.queue and abs(self.queue[0][0] - current_time) < 1e-9:
            self.queue.pop(0)
        
        if self.queue:
            self.sigma = self.queue[0][0] - current_time
            self.phase = "WAITING"
        else:
            self.sigma = float('inf')
            self.phase = "IDLE"
        self.hold_in(self.phase, self.sigma)

    def deltext(self, e):
        current_time = self.clock.get_time()
        for val in self.input["in"].values:
            self.queue.append((current_time + self.delay, val))
        self.queue.sort(key=lambda x: x[0])
        
        if self.queue:
            self.sigma = self.queue[0][0] - current_time
            self.phase = "WAITING"
        else:
            self.sigma = float('inf')
            self.phase = "IDLE"
        self.hold_in(self.phase, self.sigma)

    def exit(self):
        pass

# --- Coupled Models ---

class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        sender = Sender("sender", self)
        server_receiver = ServerReceiver("server_receiver", self)
        server_sender = ServerSender("server_sender", self)
        receiver = Receiver("receiver", self)
        
        subnet_a1 = Subnet("subnet_a1", self, DELAY_SUBNET)
        subnet_a2 = Subnet("subnet_a2", self, DELAY_SUBNET)
        subnet_b1 = Subnet("subnet_b1", self, DELAY_SUBNET)
        subnet_b2 = Subnet("subnet_b2", self, DELAY_SUBNET)
        
        self.add_component(sender)
        self.add_component(server_receiver)
        self.add_component(server_sender)
        self