#!/usr/bin/env python3
"""
Reliable Data Transfer with Alternating Bit Protocol (ABP)
"""
import argparse
import sys
import json
import logging
from collections import deque
import simpy

# Configure logging
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

class Subnet:
    """Represents a communication subnet with deterministic noise model"""
    def __init__(self, env, name, seed, delay):
        self.env = env
        self.name = name
        self.delay = delay
        self.noise_level = seed
        
    def process_packet(self, packet, channel_direction):
        """Process packet through subnet with noise model"""
        # Calculate new noise level using LCG formula
        new_noise_level = (17 * self.noise_level + 11) % 100
        
        # Determine if packet is dropped
        if new_noise_level < 10:
            # Packet dropped
            behavior = "drop"
            self.noise_level = new_noise_level
            yield self.env.timeout(0)  # No delay for dropped packet
        else:
            # Packet passes through
            behavior = "pass"
            self.noise_level = new_noise_level
            yield self.env.timeout(self.delay)  # Channel delay
            
        # Emit packet_get event
        event_data = {
            "time": self.env.now,
            "entity": "subnet",
            "event": "packet_get",
            "payload": {
                "behavior": behavior,
                "channel": channel_direction,
                "noise_value": new_noise_level
            }
        }
        print(json.dumps(event_data))
        
        return behavior

class Sender:
    """Sender entity in the ABP system"""
    def __init__(self, env, total_packets, seed, timeout, sender_delay, receiver_delay, channel_delay):
        self.env = env
        self.total_packets = total_packets
        self.timeout = timeout
        self.sender_delay = sender_delay
        self.receiver_delay = receiver_delay
        self.channel_delay = channel_delay
        self.seq_num = 1
        self.bit = 0  # Start with bit 0
        self.subnet1 = Subnet(env, "subnet1", seed, channel_delay)
        self.retransmit_count = 0
        self.ack_event = None
        
    def send_packet(self):
        """Send a packet and wait for ACK"""
        # Check if we've sent all packets
        if self.seq_num > self.total_packets:
            return
            
        # Start preparation delay
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
        
        # Create packet
        packet = Packet(self.seq_num, self.bit)
        
        # Emit packet_sent event
        event_data = {
            "time": self.env.now,
            "entity": "sender",
            "event": "packet_sent",
            "payload": {
                "seq_num": packet.seq_num,
                "bit": packet.bit,
                "is_retry": self.retransmit_count > 0
            }
        }
        print(json.dumps(event_data))
        
        # Send packet to subnet1
        yield self.env.process(self.subnet1.process_packet(packet, "forward"))
        
        # Start timer for timeout
        timeout_event = self.env.timeout(self.timeout)
        
        # Create event to wait for ACK
        ack_event = self.env.event()
        self.ack_event = ack_event
        
        # Wait for either ACK or timeout
        results = yield timeout_event | ack_event
        
        if timeout_event in results:
            # Timeout occurred, retransmit
            self.retransmit_count += 1
            logger.info(f"Timeout occurred, retransmitting packet {self.seq_num}")
            yield self.env.process(self.send_packet())
        else:
            # ACK received
            # Move to next packet
            self.seq_num += 1
            self.bit = 1 - self.bit  # Alternate bit
            self.retransmit_count = 0
            # Continue with next packet
            if self.seq_num <= self.total_packets:
                yield self.env.process(self.send_packet())
    
    def receive_ack(self, ack_bit, is_valid):
        """Receive an acknowledgment"""
        # Emit ack_received event
        event_data = {
            "time": self.env.now,
            "entity": "sender",
            "event": "ack_received",
            "payload": {
                "ack_bit": ack_bit,
                "is_valid": is_valid
            }
        }
        print(json.dumps(event_data))
        
        # Signal that ACK was received
        if self.ack_event:
            self.ack_event.succeed()

class Receiver:
    """Receiver entity in the ABP system"""
    def __init__(self, env, total_packets, seed, timeout, sender_delay, receiver_delay, channel_delay, sender):
        self.env = env
        self.total_packets = total_packets
        self.timeout = timeout
        self.sender_delay = sender_delay
        self.receiver_delay = receiver_delay
        self.channel_delay = channel_delay
        self.sender = sender
        self.subnet2 = Subnet(env, "subnet2", seed, channel_delay)
        self.received_packets = 0
        self.buffer = None
        
    def process_packet(self, packet):
        """Process received packet"""
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
        
        yield self.env.timeout(self.receiver_delay)
        
        # Process packet
        # Store in buffer (capacity 1)
        if self.buffer is None:
            self.buffer = packet
        else:
            # Buffer full, drop new packet (but we're not supposed to drop packets)
            # Just overwrite the buffer with the new packet
            self.buffer = packet
            
        # Emit packet_received event
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
        
        # Send ACK back
        ack = ACKPacket(packet.bit)
        yield self.env.process(self.subnet2.process_packet(ack, "backward"))
        
        # Clear buffer
        self.buffer = None
        self.received_packets += 1

def run_simulation(total_packets, seed, timeout, sender_delay, receiver_delay, channel_delay, simulate_time):
    """Run the ABP simulation"""
    env = simpy.Environment()
    
    # Create entities
    sender = Sender(env, total_packets, seed, timeout, sender_delay, receiver_delay, channel_delay)
    receiver = Receiver(env, total_packets, seed, timeout, sender_delay, receiver_delay, channel_delay, sender)
    
    # Set up bidirectional references
    sender.receiver = receiver
    
    # Start sender
    env.process(sender.send_packet())
    
    # Run simulation
    env.run(until=simulate_time)
    
    return env.now

def main():
    """Main function to parse arguments and run simulation"""
    parser = argparse.ArgumentParser(description='ABP Simulation')
    parser.add_argument('--total_packets', type=int, required=True, help='Total number of packets to send')
    parser.add_argument('--seed', type=int, default=42, help='Seed for noise generator')
    parser.add_argument('--timeout', type=int, default=20, help='Sender timeout duration in ms')
    parser.add_argument('--sender_delay', type=int, default=10, help='Sender preparation delay in ms')
    parser.add_argument('--receiver_delay', type=int, default=10, help='Receiver processing delay in ms')
    parser.add_argument('--channel_delay', type=int, default=3, help='Subnet transmission delay in ms')
    parser.add_argument('--simulate_time', type=int, default=1000, help='Total simulation time in ms')
    
    args = parser.parse_args()
    
    # Run simulation
    final_time = run_simulation(
        args.total_packets,
        args.seed,
        args.timeout,
        args.sender_delay,
        args.receiver_delay,
        args.channel_delay,
        args.simulate_time
    )
    
    # Print final simulation time
    print(json.dumps({
        "time": final_time,
        "entity": "system",
        "event": "simulation_end",
        "payload": {}
    }))

if __name__ == "__main__":
    main()