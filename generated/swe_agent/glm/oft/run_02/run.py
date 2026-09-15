#!/usr/bin/env python3
"""
Dropbox-like synchronization simulation using two independent ABP loops.
"""

import argparse
import sys
import json
import logging
from collections import deque
import simpy

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


class Packet:
    """Represents a data packet with sequence number and alternating bit."""
    def __init__(self, seq, bit):
        self.seq = seq
        self.bit = bit
    
    def __repr__(self):
        return f"Packet(seq={self.seq}, bit={self.bit})"


class Subnet:
    """Reliable, FIFO, fixed delay channel."""
    def __init__(self, env, name, delay_ms, output_callback):
        self.env = env
        self.name = name
        self.delay_ms = delay_ms
        self.output_callback = output_callback
        self.queue = simpy.Store(env)
        self.env.process(self.run())
    
    def send(self, packet, source, dest):
        """Send a packet through the subnet."""
        self.queue.put((packet, source, dest))
    
    def run(self):
        """Process packets with fixed delay."""
        while True:
            packet, source, dest = yield self.queue.get()
            yield self.env.timeout(self.delay_ms)
            self.output_callback(packet, source, dest)


class Sender:
    """Uploads packets to the server using ABP protocol."""
    def __init__(self, env, events, subnet_a1, subnet_a2):
        self.env = env
        self.events = events
        self.subnet_a1 = subnet_a1
        self.subnet_a2 = subnet_a2
        self.total_packets_to_send = 0
        self.packets_remaining = 0
        self.current_seq = 1
        self.current_bit = 0
        self.is_idle = True
        self.is_preparing = False
        self.waiting_for_ack = False
        self.ack_timeout_process = None
        self.control_events = []
        self.env.process(self.run())
    
    def add_control(self, num_packets, timestamp_ms):
        """Add packets to send queue."""
        self.control_events.append((timestamp_ms, num_packets))
    
    def log_event(self, event_type, val):
        """Log an event to the output queue."""
        self.events.append({
            "timestamp_ms": self.env.now,
            "model": "sender",
            "type": event_type,
            "val": val
        })
    
    def run(self):
        """Main sender loop."""
        while True:
            # Process any pending control events
            current_time = self.env.now
            events_to_process = []
            for timestamp, num_packets in self.control_events:
                if timestamp <= current_time:
                    events_to_process.append((timestamp, num_packets))
            
            for timestamp, num_packets in events_to_process:
                self.control_events.remove((timestamp, num_packets))
                self.total_packets_to_send += num_packets
                self.packets_remaining += num_packets
                self.log_event("control_cmd", {
                    "added": num_packets,
                    "total_remaining": self.packets_remaining
                })
                
                # Wake up if idle
                if self.is_idle and self.packets_remaining > 0:
                    self.is_idle = False
            
            # If we have packets to send and not currently preparing or waiting for ACK
            if self.packets_remaining > 0 and not self.is_preparing and not self.waiting_for_ack:
                # Start preparation phase
                self.is_preparing = True
                self.log_event("preparation_started", {"duration": 10000})
                yield self.env.timeout(10000)
                self.is_preparing = False
                
                # Send the packet
                packet = Packet(self.current_seq, self.current_bit)
                self.subnet_a1.send(packet, "sender", "server_receiver")
                self.log_event("packet_sent", {
                    "seq": self.current_seq,
                    "bit": self.current_bit,
                    "is_retry": False
                })
                self.waiting_for_ack = True
                
                # Start timeout timer
                self.ack_timeout_process = self.env.process(self.ack_timeout())
            
            # Small yield to allow other processes to run
            yield self.env.timeout(1)
    
    def ack_timeout(self):
        """Handle ACK timeout."""
        try:
            yield self.env.timeout(20000)
            if self.waiting_for_ack:
                self.log_event("timeout", {"seq": self.current_seq})
                # Retransmit
                packet = Packet(self.current_seq, self.current_bit)
                self.subnet_a1.send(packet, "sender", "server_receiver")
                self.log_event("packet_sent", {
                    "seq": self.current_seq,
                    "bit": self.current_bit,
                    "is_retry": True
                })
                # Restart timeout
                self.ack_timeout_process = self.env.process(self.ack_timeout())
        except simpy.Interrupt:
            # Timeout was cancelled by ACK reception
            pass
    
    def receive_ack(self, bit):
        """Handle ACK reception."""
        if self.waiting_for_ack and bit == self.current_bit:
            self.log_event("ack_received", {"bit": bit})
            self.waiting_for_ack = False
            # Cancel timeout if it's still running
            if self.ack_timeout_process is not None:
                self.ack_timeout_process.interrupt()
                self.ack_timeout_process = None
            self.current_bit = 1 - self.current_bit
            self.current_seq += 1
            self.packets_remaining -= 1
            
            if self.packets_remaining == 0:
                self.is_idle = True


class ServerReceiver:
    """Receives data from sender and stores it."""
    def __init__(self, env, events, subnet_a2, storage_queue, server_sender):
        self.env = env
        self.events = events
        self.subnet_a2 = subnet_a2
        self.storage_queue = storage_queue
        self.server_sender = server_sender
        self.expected_bit = 0
        self.received_packets = set()  # Track received packets to avoid duplicate logs
        self.env.process(self.run())
    
    def log_event(self, event_type, val):
        """Log an event to the output queue."""
        self.events.append({
            "timestamp_ms": self.env.now,
            "model": "server_receiver",
            "type": event_type,
            "val": val
        })
    
    def run(self):
        """Main server receiver loop."""
        while True:
            yield self.env.timeout(1)
    
    def receive_packet(self, packet, source, dest):
        """Handle incoming packet from sender."""
        # Only log if we haven't seen this packet before
        packet_key = (packet.seq, packet.bit)
        if packet_key not in self.received_packets:
            self.log_event("packet_received", {"seq": packet.seq, "bit": packet.bit})
            self.received_packets.add(packet_key)
        
        # Process with 3s delay
        yield self.env.timeout(3000)
        
        if packet.bit == self.expected_bit:
            # Correct packet
            self.storage_queue.put(packet)
            self.server_sender.increment_storage()
            self.subnet_a2.send(packet.bit, "server_receiver", "sender")
            self.log_event("ack_sent_to_sender", {"bit": packet.bit})
            self.expected_bit = 1 - self.expected_bit
        else:
            # Duplicate packet, resend previous ACK
            self.subnet_a2.send(1 - self.expected_bit, "server_receiver", "sender")
            self.log_event("ack_sent_to_sender", {"bit": 1 - self.expected_bit})


class ServerSender:
    """Sends stored data to receiver using ABP protocol."""
    def __init__(self, env, events, storage_queue, subnet_b1, subnet_b2):
        self.env = env
        self.events = events
        self.storage_queue = storage_queue
        self.subnet_b1 = subnet_b1
        self.subnet_b2 = subnet_b2
        self.download_allowed = False
        self.current_packet = None
        self.current_bit = 0
        self.waiting_for_ack = False
        self.request_events = []
        self.storage_count = 0  # Track number of items in storage
        self.env.process(self.run())
    
    def set_download_allowed(self, allowed, timestamp_ms):
        """Set download permission."""
        self.request_events.append((timestamp_ms, allowed))
    
    def log_event(self, event_type, val):
        """Log an event to the output queue."""
        self.events.append({
            "timestamp_ms": self.env.now,
            "model": "server_sender",
            "type": event_type,
            "val": val
        })
    
    def increment_storage(self):
        """Increment storage count."""
        self.storage_count += 1
    
    def decrement_storage(self):
        """Decrement storage count."""
        self.storage_count -= 1
    
    def run(self):
        """Main server sender loop."""
        while True:
            # Process any pending request events
            current_time = self.env.now
            events_to_process = []
            for timestamp, allowed in self.request_events:
                if timestamp <= current_time:
                    events_to_process.append((timestamp, allowed))
            
            for timestamp, allowed in events_to_process:
                self.request_events.remove((timestamp, allowed))
                if self.download_allowed != allowed:
                    self.download_allowed = allowed
                    self.log_event("download_valve_change", {"allowed": allowed})
            
            # Try to send if conditions are met
            if (self.download_allowed and 
                self.storage_count > 0 and 
                not self.waiting_for_ack):
                
                packet = yield self.storage_queue.get()
                self.decrement_storage()
                self.current_packet = packet
                self.current_bit = packet.bit
                self.subnet_b1.send(packet, "server_sender", "receiver")
                self.log_event("packet_forwarded", {
                    "seq": packet.seq,
                    "bit": packet.bit
                })
                self.waiting_for_ack = True
            
            yield self.env.timeout(1)
    
    def receive_ack(self, bit):
        """Handle ACK reception from receiver."""
        if self.waiting_for_ack and bit == self.current_bit:
            self.log_event("ack_received_from_receiver", {"bit": bit})
            self.waiting_for_ack = False
            self.current_packet = None


class Receiver:
    """Receives data from server."""
    def __init__(self, env, events, subnet_b2):
        self.env = env
        self.events = events
        self.subnet_b2 = subnet_b2
        self.env.process(self.run())
    
    def log_event(self, event_type, val):
        """Log an event to the output queue."""
        self.events.append({
            "timestamp_ms": self.env.now,
            "model": "receiver",
            "type": event_type,
            "val": val
        })
    
    def run(self):
        """Main receiver loop."""
        while True:
            yield self.env.timeout(1)
    
    def receive_packet(self, packet, source, dest):
        """Handle incoming packet from server."""
        # Process with 10s delay
        self.log_event("processing_started", {
            "seq": packet.seq,
            "duration": 10000
        })
        yield self.env.timeout(10000)
        
        # Send ACK back
        self.subnet_b2.send(packet.bit, "receiver", "server_sender")
        self.log_event("ack_sent", {"bit": packet.bit})


def parse_time(time_str):
    """Parse time string to milliseconds."""
    parts = time_str.split(':')
    if len(parts) == 3:
        # HH:MM:SS
        hours, minutes, seconds = parts
        return (int(hours) * 3600 + int(minutes) * 60 + float(seconds)) * 1000
    elif len(parts) == 4:
        # HH:MM:SS:mmm
        hours, minutes, seconds, millis = parts
        return (int(hours) * 3600 + int(minutes) * 60 + int(seconds)) * 1000 + int(millis)
    else:
        raise ValueError(f"Invalid time format: {time_str}")


def read_stdin_commands():
    """Read commands from stdin."""
    commands = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 3:
            time_str = parts[0]
            cmd_type = parts[1]
            value = parts[2]
            timestamp_ms = parse_time(time_str)
            commands.append((timestamp_ms, cmd_type, int(value)))
    return commands


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Dropbox-like synchronization simulation'
    )
    parser.add_argument(
        '--simulation_time',
        type=float,
        default=10000000.0,
        help='Simulation duration in milliseconds'
    )
    args = parser.parse_args()
    
    logger.info(f"Starting simulation with duration {args.simulation_time} ms")
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Output list for events (shared across all components)
    events = []
    
    # Storage queue for server
    storage_queue = simpy.Store(env)
    
    # Create subnets (3s delay each)
    def subnet_a1_callback(packet, source, dest):
        if dest == "server_receiver":
            env.process(server_receiver.receive_packet(packet, source, dest))
    
    def subnet_a2_callback(bit, source, dest):
        if dest == "sender":
            sender.receive_ack(bit)
    
    def subnet_b1_callback(packet, source, dest):
        if dest == "receiver":
            env.process(receiver.receive_packet(packet, source, dest))
    
    def subnet_b2_callback(bit, source, dest):
        if dest == "server_sender":
            server_sender.receive_ack(bit)
    
    subnet_a1 = Subnet(env, "A1", 3000, subnet_a1_callback)
    subnet_a2 = Subnet(env, "A2", 3000, subnet_a2_callback)
    subnet_b1 = Subnet(env, "B1", 3000, subnet_b1_callback)
    subnet_b2 = Subnet(env, "B2", 3000, subnet_b2_callback)
    
    # Create entities
    sender = Sender(env, events, subnet_a1, subnet_a2)
    server_sender = ServerSender(env, events, storage_queue, subnet_b1, subnet_b2)
    server_receiver = ServerReceiver(env, events, subnet_a2, storage_queue, server_sender)
    receiver = Receiver(env, events, subnet_b2)
    
    # Read stdin commands
    commands = read_stdin_commands()
    
    # Schedule commands
    for timestamp_ms, cmd_type, value in commands:
        if cmd_type == "control":
            sender.add_control(value, timestamp_ms)
        elif cmd_type == "request":
            server_sender.set_download_allowed(value == 1, timestamp_ms)
    
    # Run simulation
    env.run(until=args.simulation_time)
    
    # Sort events by timestamp
    events.sort(key=lambda x: x["timestamp_ms"])
    
    # Output to stdout
    for event in events:
        print(json.dumps(event))
    
    logger.info(f"Simulation completed. Total events: {len(events)}")


if __name__ == "__main__":
    main()