#!/usr/bin/env python3
"""
Reliable Data Transfer Simulation with Deterministic Noise Interference
"""
import argparse
import sys
import json
import logging
import collections
import random
import simpy

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global constants
MS = 1.0  # 1.0 simulation time unit = 1 millisecond

class Packet:
    """Represents a packet with sequence number and control bit"""
    def __init__(self, seq_num, bit):
        self.seq_num = seq_num
        self.bit = bit

class ACKPacket:
    """Represents an ACK packet with control bit"""
    def __init__(self, bit):
        self.bit = bit

class Sender:
    """Sender entity that sends packets with Alternating Bit Protocol"""
    def __init__(self, env, total_packets, seed, timeout, sender_delay, channel_delay):
        self.env = env
        self.total_packets = total_packets
        self.seed = seed
        self.timeout = timeout
        self.sender_delay = sender_delay
        self.channel_delay = channel_delay
        self.seq_num = 1
        self.current_bit = 0
        self.timer = None
        self.packet_sent = False
        self.retransmissions = 0
        self.sent_packets = []
        self.received_acks = []
        self.subnet1 = None
        self.buffer = collections.deque(maxlen=1)
        self.ack_received = False
        
    def start(self):
        """Start the sender process"""
        # Start immediately
        while self.seq_num <= self.total_packets:
            # Prepare for sending packet
            logger.debug(f"Sender preparing packet {self.seq_num}")
            
            # Emit delay_start event
            event_data = {
                "time": self.env.now,
                "entity": "sender",
                "event": "delay_start",
                "payload": {"type": "preparation", "duration": self.sender_delay}
            }
            print(json.dumps(event_data))
            
            # Wait for preparation delay
            yield self.env.timeout(self.sender_delay)
            
            # Create packet
            packet = Packet(self.seq_num, self.current_bit)
            self.sent_packets.append(packet)
            
            # Emit packet_sent event
            event_data = {
                "time": self.env.now,
                "entity": "sender",
                "event": "packet_sent",
                "payload": {"seq_num": packet.seq_num, "bit": packet.bit, "is_retry": False}
            }
            print(json.dumps(event_data))
            
            # Send packet to subnet1
            if self.subnet1:
                self.subnet1.receive_packet(packet)
            
            # Start timer
            self.timer = self.env.timeout(self.timeout)
            self.packet_sent = True
            self.ack_received = False
            
            # Wait for ACK or timeout
            yield self.timer | self.env.event()  # Wait for either ACK or timeout
            
            # Check if timeout occurred
            if self.timer.triggered:
                logger.debug(f"Timeout occurred for packet {self.seq_num}")
                # Retransmit packet
                self.retransmissions += 1
                event_data = {
                    "time": self.env.now,
                    "entity": "sender",
                    "event": "packet_sent",
                    "payload": {"seq_num": packet.seq_num, "bit": packet.bit, "is_retry": True}
                }
                print(json.dumps(event_data))
                
                # Send packet again
                if self.subnet1:
                    self.subnet1.receive_packet(packet)
                
                # Restart timer
                self.timer = self.env.timeout(self.timeout)
                yield self.timer | self.env.event()
                
                # Check if timeout occurred again
                if self.timer.triggered:
                    logger.debug(f"Timeout occurred again for packet {self.seq_num}")
                    # This should not happen in a proper simulation, but we'll handle it
                    pass
            
            # Move to next packet
            self.seq_num += 1
            self.current_bit = 1 - self.current_bit  # Alternate bit
            
        # Stop simulation
        logger.debug("Sender finished sending all packets")
        
    def receive_ack(self, ack):
        """Receive an ACK packet"""
        self.received_acks.append(ack)
        # Cancel timer if it's still running
        if self.timer and not self.timer.triggered:
            self.timer.cancel()
        
        # Emit ack_received event
        event_data = {
            "time": self.env.now,
            "entity": "sender",
            "event": "ack_received",
            "payload": {"ack_bit": ack.bit, "is_valid": True}
        }
        print(json.dumps(event_data))
        self.packet_sent = False

class Receiver:
    """Receiver entity that processes packets and sends ACKs"""
    def __init__(self, env, receiver_delay, channel_delay):
        self.env = env
        self.receiver_delay = receiver_delay
        self.channel_delay = channel_delay
        self.buffer = collections.deque(maxlen=1)
        self.subnet2 = None
        
    def process_packet(self, packet):
        """Process a received packet"""
        logger.debug(f"Receiver processing packet {packet.seq_num}")
        
        # Emit delay_start event
        event_data = {
            "time": self.env.now,
            "entity": "receiver",
            "event": "delay_start",
            "payload": {"type": "processing", "duration": self.receiver_delay}
        }
        print(json.dumps(event_data))
        
        # Wait for processing delay
        yield self.env.timeout(self.receiver_delay)
        
        # Emit packet_received event
        event_data = {
            "time": self.env.now,
            "entity": "receiver",
            "event": "packet_received",
            "payload": {"seq_num": packet.seq_num, "bit": packet.bit}
        }
        print(json.dumps(event_data))
        
        # Send ACK
        ack = ACKPacket(packet.bit)
        if self.subnet2:
            self.subnet2.receive_packet(ack)

class Subnet:
    """Subnet entity that simulates channel with deterministic noise"""
    def __init__(self, env, channel_delay, seed, direction):
        self.env = env
        self.channel_delay = channel_delay
        self.seed = seed
        self.direction = direction  # "forward" or "backward"
        self.noise_level = seed
        
    def receive_packet(self, packet):
        """Receive a packet and determine its fate"""
        # Calculate new noise level
        self.noise_level = (17 * self.noise_level + 11) % 100
        
        # Determine if packet is dropped
        if self.noise_level < 10:
            # Packet is dropped
            event_data = {
                "time": self.env.now,
                "entity": "subnet",
                "event": "packet_get",
                "payload": {"behavior": "drop", "channel": self.direction, "noise_value": self.noise_level}
            }
            print(json.dumps(event_data))
        else:
            # Packet is passed
            event_data = {
                "time": self.env.now,
                "entity": "subnet",
                "event": "packet_get",
                "payload": {"behavior": "pass", "channel": self.direction, "noise_value": self.noise_level}
            }
            print(json.dumps(event_data))
            
            # Schedule transmission after delay
            self.env.process(self.transmit_packet(packet))
            
    def transmit_packet(self, packet):
        """Transmit a packet after delay"""
        yield self.env.timeout(self.channel_delay)
        
        # Process packet based on direction
        if self.direction == "forward":
            # Forward packet to receiver
            if hasattr(self, 'receiver') and self.receiver:
                self.receiver.process_packet(packet)
        elif self.direction == "backward":
            # Backward packet to sender (ACK)
            if hasattr(self, 'sender') and self.sender:
                self.sender.receive_ack(packet)

def main():
    """Main function to run the simulation"""
    parser = argparse.ArgumentParser(description="Reliable Data Transfer Simulation")
    parser.add_argument("--total_packets", type=int, required=True, help="Total number of packets to send")
    parser.add_argument("--seed", type=int, default=42, help="Seed for noise generator")
    parser.add_argument("--timeout", type=int, default=20, help="Sender timeout duration in ms")
    parser.add_argument("--sender_delay", type=int, default=10, help="Sender preparation delay in ms")
    parser.add_argument("--receiver_delay", type=int, default=10, help="Receiver processing delay in ms")
    parser.add_argument("--channel_delay", type=int, default=3, help="Subnet transmission delay in ms")
    parser.add_argument("--simulate_time", type=int, default=1000, help="Total simulation time in ms")
    
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create entities
    sender = Sender(env, args.total_packets, args.seed, args.timeout, args.sender_delay, args.channel_delay)
    receiver = Receiver(env, args.receiver_delay, args.channel_delay)
    subnet1 = Subnet(env, args.channel_delay, args.seed, "forward")
    subnet2 = Subnet(env, args.channel_delay, args.seed, "backward")
    
    # Connect entities
    sender.subnet1 = subnet1
    receiver.subnet2 = subnet2
    subnet1.receiver = receiver
    subnet2.sender = sender
    
    # Start simulation
    env.process(sender.start())
    env.run(until=args.simulate_time)
    
    # Print final statistics
    logger.info(f"Simulation completed. Sent {sender.seq_num - 1} packets with {sender.retransmissions} retransmissions")

if __name__ == "__main__":
    main()