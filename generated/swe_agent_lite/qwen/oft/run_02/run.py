#!/usr/bin/env python3
"""
Dropbox-like synchronization simulation using Alternating Bit Protocol (ABP)
"""
import argparse
import sys
import json
import logging
import collections
import random
import simpy

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global constants
SIMULATION_TIME = 10000.0  # 10 seconds in milliseconds
PACKET_PREPARE_TIME = 10000.0  # 10 seconds in milliseconds
SERVER_PROCESSING_TIME = 3000.0  # 3 seconds in milliseconds
RECEIVER_PROCESSING_TIME = 10000.0  # 10 seconds in milliseconds
ABP_TIMEOUT = 20000.0  # 20 seconds in milliseconds

class Event:
    """Event class to represent simulation events"""
    def __init__(self, timestamp_ms, model, event_type, val):
        self.timestamp_ms = timestamp_ms
        self.model = model
        self.type = event_type
        self.val = val

    def to_json(self):
        return {
            "timestamp_ms": self.timestamp_ms,
            "model": self.model,
            "type": self.type,
            "val": self.val
        }

class Packet:
    """Packet class for ABP communication"""
    def __init__(self, seq, bit):
        self.seq = seq
        self.bit = bit

class Sender:
    """Sender (Uploader) entity"""
    def __init__(self, env, name="sender"):
        self.env = env
        self.name = name
        self.packets_remaining = 0
        self.total_packets_to_send = 0
        self.current_seq = 1
        self.current_bit = 0
        self.is_preparing = False
        self.is_sending = False
        self.last_sent_seq = 0
        self.last_sent_bit = 0
        self.last_ack_bit = 0
        self.ack_received = False
        self.timeout_event = None
        self.preparation_event = None
        self.out_events = []
        
    def control_cmd(self, added_packets):
        """Handle control command"""
        self.total_packets_to_send += int(added_packets)
        self.packets_remaining = self.total_packets_to_send
        self.out_events.append(Event(self.env.now, "sender", "control_cmd", 
                                   {"added": int(added_packets), "total_remaining": self.packets_remaining}))
        if self.packets_remaining > 0 and not self.is_preparing:
            self.is_preparing = True
            self.preparation_event = self.env.process(self.prepare_packets())
        return self.out_events
    
    def prepare_packets(self):
        """Simulate packet preparation"""
        self.out_events.append(Event(self.env.now, "sender", "preparation_started", 
                                   {"duration": PACKET_PREPARE_TIME}))
        yield self.env.timeout(PACKET_PREPARE_TIME)
        self.out_events.append(Event(self.env.now, "sender", "preparation_completed", 
                                   {"duration": PACKET_PREPARE_TIME}))
        self.is_preparing = False
        self.is_sending = True
        self.send_packet()
    
    def send_packet(self):
        """Send a packet"""
        if self.packets_remaining > 0:
            self.last_sent_seq = self.current_seq
            self.last_sent_bit = self.current_bit
            self.out_events.append(Event(self.env.now, "sender", "packet_sent", 
                                       {"seq": self.current_seq, "bit": self.current_bit, "is_retry": False}))
            self.current_seq += 1
            self.current_bit = 1 - self.current_bit  # Flip bit
            self.packets_remaining -= 1
            self.is_sending = False
            # Simulate waiting for ACK
            self.timeout_event = self.env.process(self.wait_for_ack())
        else:
            self.out_events.append(Event(self.env.now, "sender", "all_packets_sent", 
                                       {"total_sent": self.total_packets_to_send}))
    
    def wait_for_ack(self):
        """Wait for ACK with timeout"""
        yield self.env.timeout(ABP_TIMEOUT)
        # Timeout occurred
        self.out_events.append(Event(self.env.now, "sender", "timeout", 
                                   {"seq": self.last_sent_seq}))
        # Retransmit
        self.is_sending = True
        self.send_packet()
    
    def receive_ack(self, ack_bit):
        """Receive ACK"""
        self.last_ack_bit = ack_bit
        self.out_events.append(Event(self.env.now, "sender", "ack_received", 
                                   {"bit": ack_bit}))
        if ack_bit == self.current_bit:
            # Correct ACK received
            self.current_seq += 1
            self.current_bit = 1 - self.current_bit  # Flip bit
            self.packets_remaining -= 1
            if self.packets_remaining > 0:
                self.is_sending = True
                self.send_packet()
            else:
                self.out_events.append(Event(self.env.now, "sender", "all_packets_sent", 
                                           {"total_sent": self.total_packets_to_send}))
        else:
            # Wrong ACK - retransmit
            self.out_events.append(Event(self.env.now, "sender", "timeout", 
                                       {"seq": self.last_sent_seq}))
            self.is_sending = True
            self.send_packet()

class ServerReceiver:
    """Server receiver entity (ingress logic)"""
    def __init__(self, env, name="server_receiver"):
        self.env = env
        self.name = name
        self.expected_bit = 0
        self.storage_queue = collections.deque()
        self.processing_event = None
        self.processing = False
        self.out_events = []
        
    def receive_packet(self, packet):
        """Receive a packet"""
        self.out_events.append(Event(self.env.now, "server_receiver", "packet_received", 
                                   {"seq": packet.seq, "bit": packet.bit}))
        self.processing = True
        self.env.process(self.process_packet(packet))
        return self.out_events
    
    def process_packet(self, packet):
        """Process packet with 3s delay"""
        self.out_events.append(Event(self.env.now, "server_receiver", "processing_started", 
                                   {"seq": packet.seq, "duration": SERVER_PROCESSING_TIME}))
        yield self.env.timeout(SERVER_PROCESSING_TIME)
        self.out_events.append(Event(self.env.now, "server_receiver", "processing_completed", 
                                   {"seq": packet.seq, "duration": SERVER_PROCESSING_TIME}))
        
        # Check if packet bit matches expected bit
        if packet.bit == self.expected_bit:
            # Correct packet
            self.out_events.append(Event(self.env.now, "server_receiver", "ack_sent_to_sender", 
                                       {"bit": packet.bit}))
            self.storage_queue.append(packet)
            self.expected_bit = 1 - self.expected_bit  # Flip expected bit
            # Forward to server sender
            return packet
        else:
            # Duplicate packet - resend ACK
            self.out_events.append(Event(self.env.now, "server_receiver", "ack_sent_to_sender", 
                                       {"bit": 1 - packet.bit}))
            return None

class ServerSender:
    """Server sender entity (egress logic)"""
    def __init__(self, env, name="server_sender"):
        self.env = env
        self.name = name
        self.download_allowed = False
        self.storage_queue = collections.deque()
        self.is_sending = False
        self.current_seq = 0
        self.current_bit = 0
        self.waiting_for_ack = False
        self.timeout_event = None
        self.last_sent_seq = 0
        self.last_sent_bit = 0
        self.last_ack_bit = 0
        self.out_events = []
        
    def set_download_allowed(self, allowed):
        """Set download permission"""
        self.download_allowed = bool(allowed)
        self.out_events.append(Event(self.env.now, "server_sender", "download_valve_change", 
                                   {"allowed": self.download_allowed}))
        return self.out_events
    
    def receive_storage(self, packet):
        """Receive packet from storage"""
        self.storage_queue.append(packet)
        self.out_events.append(Event(self.env.now, "server_sender", "packet_forwarded", 
                                   {"seq": packet.seq, "bit": packet.bit}))
        return self.out_events
    
    def send_packet(self):
        """Send a packet from storage"""
        if len(self.storage_queue) > 0 and self.download_allowed and not self.is_sending:
            packet = self.storage_queue.popleft()
            self.current_seq = packet.seq
            self.current_bit = packet.bit
            self.is_sending = True
            self.last_sent_seq = packet.seq
            self.last_sent_bit = packet.bit
            self.out_events.append(Event(self.env.now, "server_sender", "packet_forwarded", 
                                       {"seq": packet.seq, "bit": packet.bit}))
            # Simulate waiting for ACK
            self.timeout_event = self.env.process(self.wait_for_ack())
            return packet
        return None
    
    def wait_for_ack(self):
        """Wait for ACK with timeout"""
        yield self.env.timeout(ABP_TIMEOUT)
        # Timeout occurred
        self.out_events.append(Event(self.env.now, "server_sender", "timeout", 
                                   {"seq": self.last_sent_seq}))
        # Retransmit
        self.is_sending = True
        self.send_packet()
    
    def receive_ack(self, ack_bit):
        """Receive ACK"""
        self.last_ack_bit = ack_bit
        self.out_events.append(Event(self.env.now, "server_sender", "ack_received_from_receiver", 
                                   {"bit": ack_bit}))
        if ack_bit == self.current_bit:
            # Correct ACK received
            self.is_sending = False
            self.waiting_for_ack = False
        else:
            # Wrong ACK - retransmit
            self.out_events.append(Event(self.env.now, "server_sender", "timeout", 
                                       {"seq": self.last_sent_seq}))
            self.is_sending = True
            self.send_packet()

class Receiver:
    """Receiver (Downloader) entity"""
    def __init__(self, env, name="receiver"):
        self.env = env
        self.name = name
        self.processing_event = None
        self.processing = False
        self.out_events = []
        
    def receive_packet(self, packet):
        """Receive a packet"""
        self.processing = True
        self.env.process(self.process_packet(packet))
        return self.out_events
    
    def process_packet(self, packet):
        """Process packet with 10s delay"""
        self.out_events.append(Event(self.env.now, "receiver", "processing_started", 
                                   {"seq": packet.seq, "duration": RECEIVER_PROCESSING_TIME}))
        yield self.env.timeout(RECEIVER_PROCESSING_TIME)
        self.out_events.append(Event(self.env.now, "receiver", "processing_completed", 
                                   {"seq": packet.seq, "duration": RECEIVER_PROCESSING_TIME}))
        # Send ACK back
        self.out_events.append(Event(self.env.now, "receiver", "ack_sent", 
                                   {"bit": packet.bit}))
        return packet

class Subnet:
    """Subnet with fixed 3s delay"""
    def __init__(self, env, name="subnet", delay=3000.0):
        self.env = env
        self.name = name
        self.delay = delay
        self.out_events = []
        
    def forward_data(self, data):
        """Forward data with delay"""
        yield self.env.timeout(self.delay)
        return data

def parse_time(time_str):
    """Parse time string to milliseconds"""
    try:
        # Try to parse with milliseconds
        from datetime import datetime
        time_obj = datetime.strptime(time_str, "%H:%M:%S:%f")
    except ValueError:
        # Try to parse without milliseconds
        from datetime import datetime
        time_obj = datetime.strptime(time_str, "%H:%M:%S")
    
    # Convert to milliseconds since start of day
    total_ms = (time_obj.hour * 3600000 + time_obj.minute * 60000 + time_obj.second * 1000 + time_obj.microsecond // 1000)
    return total_ms

def main():
    """Main simulation function"""
    parser = argparse.ArgumentParser(description="Dropbox-like synchronization simulation")
    parser.add_argument('--simulation_time', type=float, default=SIMULATION_TIME,
                       help='Simulation duration in milliseconds (default: 10000.0)')
    
    args = parser.parse_args()
    
    # Create SimPy environment
    env = simpy.Environment()
    
    # Create components
    sender = Sender(env)
    server_receiver = ServerReceiver(env)
    server_sender = ServerSender(env)
    receiver = Receiver(env)
    
    # Create subnets
    subnet_a1 = Subnet(env, "subnet_a1", 3000.0)  # Sender -> Server
    subnet_a2 = Subnet(env, "subnet_a2", 3000.0)  # Server -> Sender
    subnet_b1 = Subnet(env, "subnet_b1", 3000.0)  # Server -> Receiver
    subnet_b2 = Subnet(env, "subnet_b2", 3000.0)  # Receiver -> Server
    
    # Handle input from stdin
    def handle_input():
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            
            try:
                parts = line.split()
                if len(parts) < 3:
                    continue
                
                timestamp_str = parts[0]
                event_type = parts[1]
                value = parts[2]
                
                # Parse timestamp
                timestamp_ms = parse_time(timestamp_str)
                
                # Schedule event
                if event_type == "control":
                    env.process(send_control_event(timestamp_ms, value))
                elif event_type == "request":
                    env.process(send_request_event(timestamp_ms, value))
            except Exception as e:
                logger.error(f"Error processing input line: {line} - {e}")
    
    def send_control_event(timestamp_ms, value):
        """Send control event at specified time"""
        yield env.timeout(timestamp_ms)
        sender.control_cmd(value)
        logger.debug(f"Sent control event: {value} at {timestamp_ms}ms")
    
    def send_request_event(timestamp_ms, value):
        """Send request event at specified time"""
        yield env.timeout(timestamp_ms)
        server_sender.set_download_allowed(value)
        logger.debug(f"Sent request event: {value} at {timestamp_ms}ms")
    
    # Start input processing
    env.process(handle_input())
    
    # Run simulation
    logger.info(f"Starting simulation for {args.simulation_time}ms")
    env.run(until=args.simulation_time)
    
    # Print final state
    print(json.dumps({"status": "simulation_completed", "timestamp": env.now}))

if __name__ == "__main__":
    main()