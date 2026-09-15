#!/usr/bin/env python3
"""
Dropbox-like synchronization simulation using two independent ABP loops.
"""
import argparse
import sys
import json
import logging
import collections
import simpy

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global simulation time
SIMULATION_TIME = 10000.0  # 10 seconds in milliseconds

class Packet:
    """Represents a data packet in the ABP protocol."""
    
    def __init__(self, seq, bit, data=None):
        self.seq = seq
        self.bit = bit
        self.data = data

class Event:
    """Represents an event in the simulation."""
    
    def __init__(self, timestamp_ms, model, event_type, val):
        self.timestamp_ms = timestamp_ms
        self.model = model
        self.type = event_type
        self.val = val
        
    def to_json(self):
        """Convert event to JSON string."""
        return json.dumps({
            "timestamp_ms": self.timestamp_ms,
            "model": self.model,
            "type": self.type,
            "val": self.val
        })

class Sender:
    """Sender entity that uploads packets to the server."""
    
    def __init__(self, env, time_manager, server_receiver, subnet_a1):
        self.env = env
        self.time_manager = time_manager
        self.server_receiver = server_receiver
        self.subnet_a1 = subnet_a1
        self.packets_remaining = 0
        self.total_packets_to_send = 0
        self.current_bit = 0
        self.current_seq = 1
        self.is_busy = False
        
    def control_cmd(self, added_packets):
        """Handle control command to add packets to upload queue."""
        self.total_packets_to_send += added_packets
        self.packets_remaining = self.total_packets_to_send
        
        # Log the control command
        event = Event(
            self.time_manager.get_simulation_time(),
            "sender",
            "control_cmd",
            {"added": added_packets, "total_remaining": self.total_packets_to_send}
        )
        print(event.to_json())
        
        # If sender is idle, start uploading
        if not self.is_busy:
            self.start_uploading()
            
    def start_uploading(self):
        """Start the uploading process."""
        if self.packets_remaining > 0:
            self.is_busy = True
            self.env.process(self.upload_process())
            
    def upload_process(self):
        """Main upload process."""
        while self.packets_remaining > 0:
            # Preparation phase (10s)
            event = Event(
                self.time_manager.get_simulation_time(),
                "sender",
                "preparation_started",
                {"duration": 10000}
            )
            print(event.to_json())
            
            # Wait for 10 seconds preparation
            yield self.env.timeout(10000)
            
            # Send packet
            packet = Packet(self.current_seq, self.current_bit)
            event = Event(
                self.time_manager.get_simulation_time(),
                "sender",
                "packet_sent",
                {"seq": packet.seq, "bit": packet.bit, "is_retry": False}
            )
            print(event.to_json())
            
            # Send packet to server via subnet A1
            yield self.env.timeout(self.subnet_a1.delay)
            
            # Simulate waiting for ACK with timeout (20s)
            # In a real implementation, we would have a mechanism to detect ACK
            # For now, we'll simulate a successful ACK for simplicity
            yield self.env.timeout(20000)  # Timeout after 20s
            
            # For now, let's simulate a successful ACK
            event = Event(
                self.time_manager.get_simulation_time(),
                "sender",
                "ack_received",
                {"bit": packet.bit}
            )
            print(event.to_json())
            
            # Update state
            self.current_bit = 1 - self.current_bit  # Flip bit
            self.current_seq += 1
            self.packets_remaining -= 1
            
        # Upload complete
        self.is_busy = False
        self.total_packets_to_send = 0
        self.packets_remaining = 0

class ServerReceiver:
    """Server receiver that processes incoming packets from sender."""
    
    def __init__(self, env, time_manager, subnet_a2, server_sender):
        self.env = env
        self.time_manager = time_manager
        self.subnet_a2 = subnet_a2
        self.server_sender = server_sender
        self.expected_bit = 0
        self.storage_queue = collections.deque()
        self.processing_delay = 3000  # 3 seconds
        
    def receive_packet(self, packet):
        """Receive a packet from sender."""
        # Log packet arrival
        event = Event(
            self.time_manager.get_simulation_time(),
            "server_receiver",
            "packet_received",
            {"seq": packet.seq, "bit": packet.bit}
        )
        print(event.to_json())
        
        # Process packet after 3 seconds delay
        yield self.env.timeout(self.processing_delay)
        
        # Check if packet bit matches expected bit
        if packet.bit == self.expected_bit:
            # Send ACK back to sender immediately
            ack_packet = Packet(packet.seq, packet.bit)
            event = Event(
                self.time_manager.get_simulation_time(),
                "server_receiver",
                "ack_sent_to_sender",
                {"bit": ack_packet.bit}
            )
            print(event.to_json())
            
            # Push data to storage queue
            self.storage_queue.append(packet)
            
            # Flip expected bit
            self.expected_bit = 1 - self.expected_bit
            
            # Forward packet to server sender
            yield self.env.timeout(self.subnet_a2.delay)
        else:
            # Duplicate packet - resend ACK
            ack_packet = Packet(packet.seq, self.expected_bit)
            event = Event(
                self.time_manager.get_simulation_time(),
                "server_receiver",
                "ack_sent_to_sender",
                {"bit": ack_packet.bit}
            )
            print(event.to_json())
            
            # Forward packet to server sender
            yield self.env.timeout(self.subnet_a2.delay)

class ServerSender:
    """Server sender that forwards packets to receiver."""
    
    def __init__(self, env, time_manager, subnet_b1, receiver, subnet_b2):
        self.env = env
        self.time_manager = time_manager
        self.subnet_b1 = subnet_b1
        self.receiver = receiver
        self.subnet_b2 = subnet_b2
        self.storage_queue = collections.deque()
        self.download_allowed = False
        self.is_sending = False
        self.current_bit = 0
        self.current_seq = 1
        
    def download_valve_change(self, allowed):
        """Handle download valve change."""
        self.download_allowed = allowed
        
        # Log the download valve change
        event = Event(
            self.time_manager.get_simulation_time(),
            "server_sender",
            "download_valve_change",
            {"allowed": allowed}
        )
        print(event.to_json())
        
        # If download is allowed and we have packets to send, start sending
        if self.download_allowed and self.storage_queue:
            self.env.process(self.send_process())
            
    def receive_from_storage(self, packet):
        """Receive packet from storage queue."""
        self.storage_queue.append(packet)
        
        # If download is allowed and we're not already sending, start sending
        if self.download_allowed and not self.is_sending:
            self.env.process(self.send_process())
            
    def send_process(self):
        """Main send process."""
        self.is_sending = True
        while self.storage_queue and self.download_allowed:
            # Pop packet from queue
            packet = self.storage_queue.popleft()
            
            # Forward packet to receiver
            event = Event(
                self.time_manager.get_simulation_time(),
                "server_sender",
                "packet_forwarded",
                {"seq": packet.seq, "bit": packet.bit}
            )
            print(event.to_json())
            
            # Send packet to receiver via subnet B1
            yield self.env.timeout(self.subnet_b1.delay)
            
            # Simulate waiting for ACK from receiver
            yield self.env.timeout(20000)  # Timeout after 20s
            
            # For now, let's assume ACK is received
            event = Event(
                self.time_manager.get_simulation_time(),
                "server_sender",
                "ack_received_from_receiver",
                {"bit": packet.bit}
            )
            print(event.to_json())
            
            # Send ACK back to receiver via subnet B2
            ack_packet = Packet(packet.seq, packet.bit)
            yield self.env.timeout(self.subnet_b2.delay)
            
        self.is_sending = False

class Receiver:
    """Receiver entity that downloads packets from server."""
    
    def __init__(self, env, time_manager, subnet_b2):
        self.env = env
        self.time_manager = time_manager
        self.subnet_b2 = subnet_b2
        self.processing_delay = 10000  # 10 seconds
        
    def receive_packet(self, packet):
        """Receive a packet from server."""
        # Log processing start
        event = Event(
            self.time_manager.get_simulation_time(),
            "receiver",
            "processing_started",
            {"seq": packet.seq, "duration": self.processing_delay}
        )
        print(event.to_json())
        
        # Process packet for 10 seconds
        yield self.env.timeout(self.processing_delay)
        
        # Send ACK back to server
        ack_packet = Packet(packet.seq, packet.bit)
        event = Event(
            self.time_manager.get_simulation_time(),
            "receiver",
            "ack_sent",
            {"bit": ack_packet.bit}
        )
        print(event.to_json())
        
        # Send ACK via subnet B2
        yield self.env.timeout(self.subnet_b2.delay)

class Subnet:
    """Represents a network subnet with fixed delay."""
    
    def __init__(self, env, time_manager, delay=3000):  # 3 seconds delay
        self.env = env
        self.time_manager = time_manager
        self.delay = delay

def parse_input_line(line):
    """Parse input line from stdin."""
    parts = line.strip().split()
    if len(parts) < 3:
        return None
        
    timestamp = parts[0]
    event_type = parts[1]
    value = parts[2]
    
    # Convert timestamp to milliseconds
    time_parts = timestamp.split(':')
    if len(time_parts) == 4:  # HH:MM:SS:mmm format
        hours, minutes, seconds, milliseconds = map(int, time_parts)
    else:  # HH:MM:SS format
        hours, minutes, seconds = map(int, time_parts)
        milliseconds = 0
        
    timestamp_ms = (hours * 3600 + minutes * 60 + seconds) * 1000 + milliseconds
    
    return {
        "timestamp_ms": timestamp_ms,
        "type": event_type,
        "value": value
    }

def main():
    """Main simulation function."""
    parser = argparse.ArgumentParser(description='Dropbox-like synchronization simulation')
    parser.add_argument('--simulation_time', type=float, default=SIMULATION_TIME,
                        help='Simulation duration in milliseconds (default: 10000.0)')
    
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create components
    subnet_a1 = Subnet(env, None, 3000)  # Sender -> Server
    subnet_a2 = Subnet(env, None, 3000)  # Server -> Sender
    subnet_b1 = Subnet(env, None, 3000)  # Server -> Receiver
    subnet_b2 = Subnet(env, None, 3000)  # Receiver -> Server
    
    # Create entities
    server_receiver = ServerReceiver(env, None, subnet_a2, None)
    server_sender = ServerSender(env, None, subnet_b1, None, subnet_b2)
    receiver = Receiver(env, None, subnet_b2)
    sender = Sender(env, None, server_receiver, subnet_a1)
    
    # Connect components
    server_receiver.server_sender = server_sender
    server_sender.receiver = receiver
    
    # Process input from stdin
    for line in sys.stdin:
        if not line.strip():
            continue
            
        parsed = parse_input_line(line)
        if not parsed:
            continue
            
        # Schedule events based on timestamp
        timestamp_ms = parsed["timestamp_ms"]
        event_type = parsed["type"]
        value = parsed["value"]
        
        # Schedule the event at the specified time
        if event_type == "control":
            # Add to sender's upload queue
            env.process(sender.control_cmd(int(value)))
        elif event_type == "request":
            # Toggle download permission
            allowed = bool(int(value))
            env.process(server_sender.download_valve_change(allowed))
    
    # Run simulation
    env.run(until=args.simulation_time)
    
    # Print final state
    final_state = {
        "timestamp_ms": args.simulation_time,
        "model": "final_state",
        "type": "simulation_ended",
        "val": {}
    }
    print(json.dumps(final_state))

if __name__ == "__main__":
    main()