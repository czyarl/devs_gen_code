#!/usr/bin/env python3
"""
Dropbox-like synchronization simulation using two independent ABP loops.
"""

import argparse
import sys
import json
import logging
import collections
import random
import simpy

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Packet:
    def __init__(self, seq, bit):
        self.seq = seq
        self.bit = bit

class Event:
    def __init__(self, timestamp_ms, model, event_type, val):
        self.timestamp_ms = timestamp_ms
        self.model = model
        self.type = event_type
        self.val = val

    def to_json(self):
        return json.dumps({
            "timestamp_ms": self.timestamp_ms,
            "model": self.model,
            "type": self.type,
            "val": self.val
        })

def parse_time(time_str):
    """Parse time string in format HH:MM:SS or HH:MM:SS:mmm"""
    if ':' in time_str:
        parts = time_str.split(':')
        if len(parts) == 4:
            # HH:MM:SS:mmm format
            hours, minutes, seconds, milliseconds = map(int, parts)
        else:
            # HH:MM:SS format
            hours, minutes, seconds = map(int, parts)
            milliseconds = 0
        return (hours * 3600 + minutes * 60 + seconds) * 1000 + milliseconds
    return 0

class Subnet:
    def __init__(self, env, delay=3000):
        self.env = env
        self.delay = delay  # in milliseconds
        
    def send(self, packet):
        # Simulate transmission delay
        yield self.env.timeout(self.delay)
        return packet

class Sender:
    def __init__(self, env, server_receiver, subnet_a1, subnet_a2, event_queue):
        self.env = env
        self.server_receiver = server_receiver
        self.subnet_a1 = subnet_a1
        self.subnet_a2 = subnet_a2
        self.event_queue = event_queue
        self.packets_remaining = 0
        self.total_packets_to_send = 0
        self.is_idle = True
        self.current_bit = 0
        self.current_seq = 1
        
    def control_cmd(self, n):
        """Handle control command to add packets to upload queue"""
        self.total_packets_to_send += n
        self.packets_remaining = self.total_packets_to_send
        
        # If sender was idle, start uploading
        if self.is_idle:
            self.is_idle = False
            self.env.process(self.upload_loop())
        
        # Log the control command
        self.event_queue.append(Event(
            self.env.now,
            "sender",
            "control_cmd",
            {"added": n, "total_remaining": self.total_packets_to_send}
        ))
        
    def upload_loop(self):
        """Main upload loop for the sender"""
        while self.packets_remaining > 0:
            # Prepare for sending (10s delay)
            self.event_queue.append(Event(
                self.env.now,
                "sender",
                "preparation_started",
                {"duration": 10000}
            ))
            
            yield self.env.timeout(10000)  # 10 seconds preparation
            
            # Send packet
            packet = Packet(self.current_seq, self.current_bit)
            self.event_queue.append(Event(
                self.env.now,
                "sender",
                "packet_sent",
                {"seq": packet.seq, "bit": packet.bit, "is_retry": False}
            ))
            
            # Simulate the send operation
            yield self.env.timeout(3000)  # Simulate subnet delay
            
            # Simulate ACK handling
            self.event_queue.append(Event(
                self.env.now,
                "sender",
                "ack_received",
                {"bit": packet.bit}
            ))
            
            # Update state
            self.current_bit = 1 - self.current_bit  # Flip bit
            self.current_seq += 1
            self.packets_remaining -= 1
            
            # If no more packets, go idle
            if self.packets_remaining <= 0:
                self.is_idle = True
                break

class ServerReceiver:
    def __init__(self, env, sender, subnet_a1, subnet_a2, event_queue):
        self.env = env
        self.sender = sender
        self.subnet_a1 = subnet_a1
        self.subnet_a2 = subnet_a2
        self.event_queue = event_queue
        self.expected_bit = 0
        self.storage_queue = []
        
    def receive_packet(self, packet):
        """Receive packet from sender"""
        self.event_queue.append(Event(
            self.env.now,
            "server_receiver",
            "packet_received",
            {"seq": packet.seq, "bit": packet.bit}
        ))
        
        # Process with 3s delay
        yield self.env.timeout(3000)
        
        # Check if bit matches expected bit
        if packet.bit == self.expected_bit:
            # Send ACK back to sender
            ack_packet = Packet(packet.seq, packet.bit)
            self.event_queue.append(Event(
                self.env.now,
                "server_receiver",
                "ack_sent_to_sender",
                {"bit": ack_packet.bit}
            ))
            
            # Store packet in queue
            self.storage_queue.append(packet)
            
            # Flip expected bit
            self.expected_bit = 1 - self.expected_bit
        else:
            # Duplicate packet - resend ACK
            ack_packet = Packet(packet.seq, 1 - packet.bit)  # Previous bit
            self.event_queue.append(Event(
                self.env.now,
                "server_receiver",
                "ack_sent_to_sender",
                {"bit": ack_packet.bit}
            ))

class ServerSender:
    def __init__(self, env, server_receiver, receiver, subnet_b1, subnet_b2, event_queue):
        self.env = env
        self.server_receiver = server_receiver
        self.receiver = receiver
        self.subnet_b1 = subnet_b1
        self.subnet_b2 = subnet_b2
        self.event_queue = event_queue
        self.download_allowed = False
        
    def download_valve_change(self, allowed):
        """Handle download valve change"""
        self.download_allowed = allowed
        
        self.event_queue.append(Event(
            self.env.now,
            "server_sender",
            "download_valve_change",
            {"allowed": allowed}
        ))
        
        # If download is enabled, start forwarding packets
        if allowed:
            self.env.process(self.forward_packets())
        
    def forward_packets(self):
        """Forward packets from storage to receiver"""
        while self.download_allowed and self.server_receiver.storage_queue:
            # Get packet from storage
            packet = self.server_receiver.storage_queue.pop(0)
            
            # Forward packet to receiver
            self.event_queue.append(Event(
                self.env.now,
                "server_sender",
                "packet_forwarded",
                {"seq": packet.seq, "bit": packet.bit}
            ))
            
            # Simulate the subnet delay
            yield self.env.timeout(3000)  # Simulate the subnet delay
            
            # Simulate ACK handling
            self.event_queue.append(Event(
                self.env.now,
                "server_sender",
                "ack_received_from_receiver",
                {"bit": packet.bit}
            ))

class Receiver:
    def __init__(self, env, server_sender, subnet_b1, subnet_b2, event_queue):
        self.env = env
        self.server_sender = server_sender
        self.subnet_b1 = subnet_b1
        self.subnet_b2 = subnet_b2
        self.event_queue = event_queue
        
    def receive_packet(self, packet):
        """Receive packet from server"""
        self.event_queue.append(Event(
            self.env.now,
            "receiver",
            "processing_started",
            {"seq": packet.seq, "duration": 10000}
        ))
        
        # Process with 10s delay
        yield self.env.timeout(10000)
        
        # Send ACK back to server
        self.event_queue.append(Event(
            self.env.now,
            "receiver",
            "ack_sent",
            {"bit": packet.bit}
        ))

def main():
    parser = argparse.ArgumentParser(description='Dropbox-like synchronization simulation')
    parser.add_argument('--simulation_time', type=float, default=10000000.0, 
                       help='Simulation duration in milliseconds (default: 10000000.0)')
    
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create event queue
    event_queue = []
    
    # Create subnets
    subnet_a1 = Subnet(env, 3000)  # 3s delay
    subnet_a2 = Subnet(env, 3000)  # 3s delay
    subnet_b1 = Subnet(env, 3000)  # 3s delay
    subnet_b2 = Subnet(env, 3000)  # 3s delay
    
    # Create entities
    sender = Sender(env, None, subnet_a1, subnet_a2, event_queue)
    server_receiver = ServerReceiver(env, sender, subnet_a1, subnet_a2, event_queue)
    server_sender = ServerSender(env, server_receiver, None, subnet_b1, subnet_b2, event_queue)
    receiver = Receiver(env, server_sender, subnet_b1, subnet_b2, event_queue)
    
    # Connect entities
    sender.server_receiver = server_receiver
    server_receiver.sender = sender
    server_sender.receiver = receiver
    receiver.server_sender = server_sender
    
    # Process input from stdin
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
            
        parts = line.split()
        if len(parts) < 3:
            continue
            
        timestamp_str = parts[0]
        event_type = parts[1]
        value = parts[2]
        
        # Parse timestamp
        timestamp_ms = parse_time(timestamp_str)
        
        # Schedule events
        if event_type == "control":
            env.process(delayed_control(env, sender, int(value), timestamp_ms))
        elif event_type == "request":
            env.process(delayed_request(env, server_sender, int(value), timestamp_ms))
    
    # Run simulation
    env.run(until=args.simulation_time)
    
    # Output events
    for event in event_queue:
        print(event.to_json())

def delayed_control(env, sender, value, timestamp_ms):
    """Delay control command until specified time"""
    yield env.timeout(timestamp_ms)
    sender.control_cmd(value)

def delayed_request(env, server_sender, value, timestamp_ms):
    """Delay request command until specified time"""
    yield env.timeout(timestamp_ms)
    server_sender.download_valve_change(bool(value))

if __name__ == "__main__":
    main()