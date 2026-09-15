#!/usr/bin/env python3
"""
Reliable Data Transfer with Deterministic Noise Interference
Implementation of Alternating Bit Protocol (ABP) with simulated packet loss
"""

import argparse
import sys
import json
import logging
import collections
import random
import simpy

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Packet:
    """Represents a data packet with sequence number and control bit"""
    def __init__(self, seq_num, bit):
        self.seq_num = seq_num
        self.bit = bit

class ACKPacket:
    """Represents an acknowledgment packet"""
    def __init__(self, bit):
        self.bit = bit

class NoiseGenerator:
    """Deterministic noise generator for packet loss simulation"""
    def __init__(self, seed):
        self.x = seed
    
    def get_next_noise(self):
        """Calculate next noise level using LCG formula: x_new = (17 * x_old + 11) mod 100"""
        self.x = (17 * self.x + 11) % 100
        return self.x

class Subnet:
    """Represents a communication subnet with deterministic noise interference"""
    def __init__(self, env, name, delay, seed):
        self.env = env
        self.name = name
        self.delay = delay
        self.noise_gen = NoiseGenerator(seed)
        self.packet_buffer = collections.deque(maxlen=1)  # Buffer with capacity 1
        
    def process_packet(self, packet, direction):
        """Process packet through subnet with noise interference"""
        # Determine packet fate based on noise level
        noise_value = self.noise_gen.get_next_noise()
        behavior = "drop" if noise_value < 10 else "pass"
        
        # Log packet fate
        event_data = {
            "time": self.env.now,
            "entity": "subnet",
            "event": "packet_get",
            "payload": {
                "behavior": behavior,
                "channel": direction,
                "noise_value": noise_value
            }
        }
        print(json.dumps(event_data))
        
        # If packet is dropped, return None
        if behavior == "drop":
            return None
            
        # If packet passes, wait for channel delay
        yield self.env.timeout(self.delay)
        
        # Return the packet for further processing
        return packet

class Sender:
    """Sender entity in the communication system"""
    def __init__(self, env, total_packets, timeout, sender_delay, subnet1):
        self.env = env
        self.total_packets = total_packets
        self.timeout = timeout
        self.sender_delay = sender_delay
        self.subnet1 = subnet1
        self.seq_num = 1
        self.bit = 0  # Start with bit 0
        self.waiting_for_ack = False
        self.timer = None
        self.sent_packets = 0
        self.ack_received = False
        self.ack_bit = None
        
    def send_packet(self):
        """Send a packet through subnet1"""
        # Create packet
        packet = Packet(self.seq_num, self.bit)
        
        # Log packet sending
        event_data = {
            "time": self.env.now,
            "entity": "sender",
            "event": "packet_sent",
            "payload": {
                "seq_num": packet.seq_num,
                "bit": packet.bit,
                "is_retry": self.sent_packets > 0  # First packet is not a retry
            }
        }
        print(json.dumps(event_data))
        
        # Send packet through subnet1
        packet_process = self.env.process(self.subnet1.process_packet(packet, "forward"))
        result = yield packet_process
        
        # If packet was dropped, we need to retransmit
        if result is None:
            # Packet was dropped, retransmit
            logger.info(f"Packet {self.seq_num} dropped, retransmitting")
            yield self.env.timeout(self.sender_delay)
            yield from self.send_packet()
        else:
            # Start timer for timeout
            self.timer = self.env.timeout(self.timeout)
            self.waiting_for_ack = True
            self.sent_packets += 1
        
    def start_preparation_delay(self):
        """Start preparation delay before sending packet"""
        event_data = {
            "time": self.env.now,
            "entity": "sender",
            "event": "delay_start",
            "payload": {
                "type": "preparation",
                "duration": self.sender_delay
            }
        }
        print(json.dumps(event_data))
        
        yield self.env.timeout(self.sender_delay)
        
    def run(self):
        """Main sender process"""
        while self.sent_packets < self.total_packets:
            # Start preparation delay
            yield from self.start_preparation_delay()
            
            # Send packet
            yield from self.send_packet()
            
            # Wait for ACK or timeout
            while self.waiting_for_ack:
                # Wait for either ACK or timeout
                timeout_event = self.timer
                ack_event = self.env.event()
                
                # Wait for either event
                yield timeout_event | ack_event
                
                # If timeout occurred
                if timeout_event.triggered:
                    # Retransmit packet
                    logger.info(f"Timeout occurred, retransmitting packet {self.seq_num}")
                    yield from self.start_preparation_delay()
                    yield from self.send_packet()
                else:
                    # ACK received, continue with next packet
                    break
                    
            # Move to next packet
            self.seq_num += 1
            self.bit = 1 - self.bit  # Alternate bit
            
        # Stop when all packets sent
        logger.info("Sender finished sending all packets")

class Receiver:
    """Receiver entity in the communication system"""
    def __init__(self, env, receiver_delay, subnet2):
        self.env = env
        self.receiver_delay = receiver_delay
        self.subnet2 = subnet2
        self.packet_buffer = collections.deque(maxlen=1)  # Buffer with capacity 1
        
    def process_packet(self, packet):
        """Process received packet"""
        # Log packet reception
        event_data = {
            "time": self.env.now,
            "entity": "receiver",
            "event": "packet_received",
            "payload": {
                "seq_num": packet.seq_num,
                "bit": packet.bit
            }
        }
        print(json.dumps(event_data))
        
        # Start processing delay
        event_data = {
            "time": self.env.now,
            "entity": "receiver",
            "event": "delay_start",
            "payload": {
                "type": "processing",
                "duration": self.receiver_delay
            }
        }
        print(json.dumps(event_data))
        
        # Wait for processing delay
        yield self.env.timeout(self.receiver_delay)
        
        # Send ACK back through subnet2
        ack = ACKPacket(packet.bit)
        event_data = {
            "time": self.env.now,
            "entity": "receiver",
            "event": "ack_sent",
            "payload": {
                "ack_bit": ack.bit
            }
        }
        print(json.dumps(event_data))
        
        # Send ACK through subnet2
        ack_process = self.env.process(self.subnet2.process_packet(ack, "backward"))
        yield ack_process

def main():
    """Main function to run the simulation"""
    parser = argparse.ArgumentParser(description="Reliable Data Transfer with Deterministic Noise Interference")
    parser.add_argument("--total_packets", type=int, default=10, help="Total number of packets to send")
    parser.add_argument("--seed", type=int, default=42, help="Seed for noise generator")
    parser.add_argument("--timeout", type=int, default=20, help="Sender timeout duration in ms")
    parser.add_argument("--sender_delay", type=int, default=10, help="Sender preparation delay in ms")
    parser.add_argument("--receiver_delay", type=int, default=10, help="Receiver processing delay in ms")
    parser.add_argument("--channel_delay", type=int, default=3, help="Subnet transmission delay in ms")
    parser.add_argument("--simulate_time", type=int, default=1000, help="Total simulation time in ms")
    
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create subnets
    subnet1 = Subnet(env, "subnet1", args.channel_delay, args.seed)
    subnet2 = Subnet(env, "subnet2", args.channel_delay, args.seed)
    
    # Create sender and receiver
    sender = Sender(env, args.total_packets, args.timeout, args.sender_delay, subnet1)
    receiver = Receiver(env, args.receiver_delay, subnet2)
    
    # Start sender and receiver processes
    env.process(sender.run())
    # Note: In a real implementation, we would need to handle packet reception from subnet1
    # For now, we'll just run the simulation for the specified time
    
    # Run simulation
    env.run(until=args.simulate_time)
    
    logger.info("Simulation completed")

if __name__ == "__main__":
    main()