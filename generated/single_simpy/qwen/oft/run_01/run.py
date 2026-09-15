```python
import argparse
import sys
import json
import logging
import time
from collections import deque
from typing import Optional, List
import simpy

# Global simulation environment
env = simpy.Environment()

# Event types
EVENT_TYPES = {
    "control_cmd": "sender",
    "download_valve_change": "server_sender",
    "preparation_started": "sender",
    "packet_sent": "sender",
    "ack_received": "sender",
    "timeout": "sender",
    "packet_received": "server_receiver",
    "ack_sent_to_sender": "server_receiver",
    "packet_forwarded": "server_sender",
    "ack_received_from_receiver": "server_sender",
    "processing_started": "receiver",
    "ack_sent": "receiver"
}

class EventLogger:
    def __init__(self):
        self.events = []
    
    def log(self, model: str, event_type: str, val: dict):
        event = {
            "timestamp_ms": env.now,
            "model": model,
            "type": event_type,
            "val": val
        }
        self.events.append(event)
        print(json.dumps(event), file=sys.stdout)

# Global logger
logger = EventLogger()

class Packet:
    def __init__(self, seq: int, bit: int):
        self.seq = seq
        self.bit = bit

class Subnet:
    def __init__(self, env, delay: float):
        self.env = env
        self.delay = delay
        self.queue = deque()
    
    def send(self, data):
        yield self.env.timeout(self.delay)
        return data

class Sender:
    def __init__(self, env, server_receiver, server_sender, subnet_a1, subnet_a2):
        self.env = env
        self.server_receiver = server_receiver
        self.server_sender = server_sender
        self.subnet_a1 = subnet_a1
        self.subnet_a2 = subnet_a2
        self.packets_remaining = 0
        self.total_packets_to_send = 0
        self.current_bit = 0
        self.current_seq = 1
        self.is_busy = False
        self.timeout_duration = 20000  # 20 seconds in milliseconds
        self.preparation_duration = 10000  # 10 seconds in milliseconds
        
    def control_cmd(self, added: int):
        self.total_packets_to_send += added
        logger.log("sender", "control_cmd", {"added": added, "total_remaining": self.total_packets_to_send})
        if not self.is_busy and self.total_packets_to_send > 0:
            self.env.process(self.upload_packets())
    
    def upload_packets(self):
        self.is_busy = True
        logger.log("sender", "preparation_started", {"duration": self.preparation_duration})
        yield self.env.timeout(self.preparation_duration)
        
        while self.total_packets_to_send > 0:
            # Send packet
            packet = Packet(self.current_seq, self.current_bit)
            logger.log("sender", "packet_sent", {"seq": packet.seq, "bit": packet.bit, "is_retry": False})
            
            # Send to server
            ack = yield self.env.process(self.send_packet_to_server(packet))
            
            # Wait for ACK or timeout
            timeout_event = self.env.timeout(self.timeout_duration)
            ack_event = self.env.event()
            ack_event.callbacks.append(lambda e: ack_event.succeed())
            done_event = yield timeout_event | ack_event
            
            if done_event is timeout_event:
                # Timeout occurred
                logger.log("sender", "timeout", {"seq": packet.seq})
                # Retry sending the same packet
                logger.log("sender", "packet_sent", {"seq": packet.seq, "bit": packet.bit, "is_retry": True})
                ack = yield self.env.process(self.send_packet_to_server(packet))
                
            # Process ACK
            if ack.bit == self.current_bit:
                # ACK matches expected bit
                logger.log("sender", "ack_received", {"bit": ack.bit})
                self.current_bit = 1 - self.current_bit  # Flip bit
                self.current_seq += 1
                self.total_packets_to_send -= 1
            else:
                # ACK mismatch (duplicate)
                logger.log("sender", "ack_received", {"bit": ack.bit})
                # Do not increment seq or decrement total_packets_to_send
        
        self.is_busy = False
        
    def send_packet_to_server(self, packet):
        # Send to subnet A1
        yield self.env.process(self.subnet_a1.send(packet))
        # Simulate sending to server
        yield self.env.timeout(0)  # Immediate processing
        # Receive ACK from server receiver
        ack = Packet(0, packet.bit)  # ACK with same bit
        return ack

class ServerReceiver:
    def __init__(self, env, subnet_a1, subnet_a2, server_sender):
        self.env = env
        self.subnet_a1 = subnet_a1
        self.subnet_a2 = subnet_a2
        self.server_sender = server_sender
        self.expected_bit = 0
        self.storage_queue = deque()
        
    def receive_packet(self, packet):
        logger.log("server_receiver", "packet_received", {"seq": packet.seq, "bit": packet.bit})
        
        # Simulate processing delay
        yield self.env.timeout(3000)  # 3 seconds processing
        
        # Check if packet is valid
        if packet.bit == self.expected_bit:
            # Valid packet
            self.storage_queue.append(packet)
            logger.log("server_receiver", "ack_sent_to_sender", {"bit": packet.bit})
            self.expected_bit = 1 - self.expected_bit  # Flip expected bit
        else:
            # Duplicate packet
            logger.log("server_receiver", "ack_sent_to_sender", {"bit": self.expected_bit})
            
    def process_packets(self):
        while True:
            if self.storage_queue:
                packet = self.storage_queue.popleft()
                # Forward packet to server sender
                yield self.env.process(self.server_sender.forward_packet(packet))
            else:
                yield self.env.timeout(1000)  # Wait for new packets

class ServerSender:
    def __init__(self, env, server_receiver, subnet_b1, subnet_b2):
        self.env = env
        self.server_receiver = server_receiver
        self.subnet_b1 = subnet_b1
        self.subnet_b2 = subnet_b2
        self.storage_queue = deque()
        self.download_allowed = False
        self.is_sending = False
        self.current_bit = 0
        
    def download_valve_change(self, allowed: bool):
        self.download_allowed = allowed
        logger.log("server_sender", "download_valve_change", {"allowed": allowed})
        
    def forward_packet(self, packet):
        # Send packet to subnet B1
        yield self.env.process(self.subnet_b1.send(packet))
        # Simulate sending to receiver
        yield self.env.timeout(0)  # Immediate processing
        # Receive ACK from receiver
        ack = Packet(0, packet.bit)  # ACK with same bit
        logger.log("server_sender", "ack_received_from_receiver", {"bit": ack.bit})
        
    def process_packets(self):
        while True:
            if self.download_allowed and self.storage_queue and not self.is_sending:
                self.is_sending = True
                packet = self.storage_queue.popleft()
                logger.log("server_sender", "packet_forwarded", {"seq": packet.seq, "bit": packet.bit})
                # Forward packet to receiver
                yield self.env.process(self.forward_packet(packet))
                self.is_sending = False
            else:
                yield self.env.timeout(1000)  # Wait for new conditions

class Receiver:
    def __init__(self, env, subnet_b1, subnet_b2):
        self.env = env
        self.subnet_b1 = subnet_b1
        self.subnet_b2 = subnet_b2
        self.is_processing = False
        
    def receive_packet(self, packet):
        self.is_processing = True
        logger.log("receiver", "processing_started", {"seq": packet.seq, "duration": 10000})
        # Simulate processing delay
        yield self.env.timeout(10000)  # 10 seconds processing
        logger.log("receiver", "ack_sent", {"bit": packet.bit})
        self.is_processing = False

def parse_time(time_str):
    # Parse time string like "00:00:10:000" to milliseconds
    h, m, s, ms = map(int, time_str.split(':'))
    return (h * 3600 + m * 60 + s) * 1000 + ms

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulation_time', type=float, default=10000000.0, help='Simulation duration in milliseconds')
    args = parser.parse_args()
    
    # Create simulation components
    subnet_a1 = Subnet(env, 3000)  # 3 seconds delay
    subnet_a2 = Subnet(env, 3000)
    subnet_b1 = Subnet(env, 3000)
    subnet_b2 = Subnet(env, 3000)
    
    server_receiver = ServerReceiver(env, subnet_a1, subnet_a2, None)
    server_sender = ServerSender(env, server_receiver, subnet_b1, subnet_b2)
    receiver = Receiver(env, subnet_b1, subnet_b2)
    sender = Sender(env, server_receiver, server_sender, subnet_a1, subnet_a2)
    
    # Set up server sender to point back to server receiver
    server_receiver.server_sender = server_sender
    
    # Start processing threads
    env.process(server_receiver.process_packets())
    env.process(server_sender.process_packets())
    
    # Process input from stdin
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
            
        parts = line.split()
        if len(parts) != 3:
            continue
            
        time_str, cmd_type, value_str = parts
        timestamp = parse_time(time_str)
        
        if cmd_type == "control":
            added = int(value_str)
            env.process(env.timeout(timestamp).then(lambda _: sender.control_cmd(added)))
        elif cmd_type == "request":
            allowed = bool(int(value_str))
            env.process(env.timeout(timestamp).then(lambda _: server_sender.download_valve_change(allowed)))
    
    # Run simulation
    env.run(until=args.simulation_time)
    
    # Print events
    for event in logger.events:
        print(json.dumps(event), file=sys.stdout)

if __name__ == "__main__":
    main()
</python_code>