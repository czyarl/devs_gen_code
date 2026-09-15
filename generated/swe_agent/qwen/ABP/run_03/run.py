#!/usr/bin/env python3
"""
Reliable Data Transfer with Deterministic Noise Interference
Implementation of Alternating Bit Protocol (ABP) simulation
"""

import argparse
import sys
import json
import logging
from collections import deque
import random
import simpy


# Global constants
DEFAULT_SEED = 42
DEFAULT_TIMEOUT = 20
DEFAULT_SENDER_DELAY = 10
DEFAULT_RECEIVER_DELAY = 10
DEFAULT_CHANNEL_DELAY = 3
DEFAULT_SIMULATE_TIME = 1000


class Event:
    """Event class to represent simulation events"""
    def __init__(self, time, entity, event_type, payload):
        self.time = time
        self.entity = entity
        self.event_type = event_type
        self.payload = payload

    def to_json(self):
        return json.dumps({
            "time": self.time,
            "entity": self.entity,
            "event": self.event_type,
            "payload": self.payload
        })


class Packet:
    """Packet class to represent data packets"""
    def __init__(self, seq_num, bit, is_retry=False):
        self.seq_num = seq_num
        self.bit = bit
        self.is_retry = is_retry


class Subnet:
    """Subnet (channel) with deterministic noise interference"""
    def __init__(self, env, name, seed, delay, channel_type):
        self.env = env
        self.name = name
        self.seed = seed
        self.delay = delay
        self.channel_type = channel_type  # "forward" or "backward"
        self.noise_level = seed
        self.receiver = None  # Will be set by Simulation
        self.sender = None  # Will be set by Simulation
        
    def send_packet(self, packet):
        """Send packet through subnet with noise interference"""
        # Process packet with noise interference
        # Calculate new noise level
        new_noise_level = (17 * self.noise_level + 11) % 100
        
        # Determine if packet is dropped
        if new_noise_level < 10:
            # Packet dropped
            event = Event(self.env.now, "subnet", "packet_get", {
                "behavior": "drop",
                "channel": self.channel_type,
                "noise_value": new_noise_level
            })
            print(event.to_json())
            self.noise_level = new_noise_level
            # Return a generator that does nothing (just yields)
            yield self.env.timeout(0)
            return
        else:
            # Packet passed
            event = Event(self.env.now, "subnet", "packet_get", {
                "behavior": "pass",
                "channel": self.channel_type,
                "noise_value": new_noise_level
            })
            print(event.to_json())
            self.noise_level = new_noise_level
            
            # Wait for channel delay
            yield self.env.timeout(self.delay)
            
            # If this is the forward channel, deliver to receiver
            if self.channel_type == "forward" and self.receiver:
                yield self.env.process(self.receiver.receive_packet(packet))
            # If this is the backward channel, deliver to sender
            elif self.channel_type == "backward" and self.sender:
                # For ACK packets, deliver to sender
                yield self.env.process(self.sender.receive_ack(packet))
            
            return


class Sender:
    """Sender entity in the ABP system"""
    def __init__(self, env, total_packets, seed, timeout, sender_delay, subnet1):
        self.env = env
        self.total_packets = total_packets
        self.seed = seed
        self.timeout = timeout
        self.sender_delay = sender_delay
        self.subnet1 = subnet1
        self.seq_num = 1
        self.current_bit = 0
        self.timer_active = False
        self.retransmit_count = 0
        
    def send_packet(self):
        """Send a packet through subnet1"""
        # Create packet
        packet = Packet(self.seq_num, self.current_bit, self.retransmit_count > 0)
        
        # Start preparation delay
        event = Event(self.env.now, "sender", "delay_start", {
            "type": "preparation",
            "duration": self.sender_delay
        })
        print(event.to_json())
        
        # Wait for preparation delay
        yield self.env.timeout(self.sender_delay)
        
        # Send packet
        event = Event(self.env.now, "sender", "packet_sent", {
            "seq_num": packet.seq_num,
            "bit": packet.bit,
            "is_retry": packet.is_retry
        })
        print(event.to_json())
        
        # Send to subnet1
        # We'll handle the case where send_packet returns a generator or not
        try:
            result = self.subnet1.send_packet(packet)
            if hasattr(result, '__iter__') and hasattr(result, '__next__'):
                # It's a generator, yield it
                yield self.env.process(result)
            else:
                # It's not a generator, just continue
                pass
        except Exception as e:
            # If there's an error, just continue
            pass
        
        # Start timer
        self.timer_active = True
        timer_process = self.env.process(self.timer())
        
        # Wait for timer to complete or ACK
        yield timer_process
        
        # If timer expired, retransmit
        if self.timer_active:
            self.retransmit_count += 1
            self.seq_num -= 1  # Retransmit same packet
            self.current_bit = 1 - self.current_bit  # Flip bit
            self.send_packet()
    
    def timer(self):
        """Timer process"""
        yield self.env.timeout(self.timeout)
        if self.timer_active:
            self.timer_active = False
            # Timer expired, retransmit
            pass
    
    def receive_ack(self, ack_packet):
        """Receive acknowledgment"""
        # Check if this is a valid ACK
        is_valid = ack_packet.bit == self.current_bit  # Valid if bit matches current packet bit
        
        event = Event(self.env.now, "sender", "ack_received", {
            "ack_bit": ack_packet.bit,
            "is_valid": is_valid
        })
        print(event.to_json())
        
        if is_valid:
            self.timer_active = False
            self.seq_num += 1
            self.current_bit = 1 - self.current_bit  # Flip bit
            self.retransmit_count = 0
            if self.seq_num <= self.total_packets:
                self.send_packet()
        else:
            # Invalid ACK, retransmit
            self.seq_num -= 1  # Retransmit same packet
            self.current_bit = 1 - self.current_bit  # Flip bit
            self.send_packet()


class Receiver:
    """Receiver entity in the ABP system"""
    def __init__(self, env, receiver_delay, subnet2):
        self.env = env
        self.receiver_delay = receiver_delay
        self.subnet2 = subnet2
        self.packet_buffer = None
        
    def receive_packet(self, packet):
        """Receive a packet"""
        # Start processing delay
        event = Event(self.env.now, "receiver", "delay_start", {
            "type": "processing",
            "duration": self.receiver_delay
        })
        print(event.to_json())
        
        # Wait for processing delay
        yield self.env.timeout(self.receiver_delay)
        
        # Process packet
        event = Event(self.env.now, "receiver", "packet_received", {
            "seq_num": packet.seq_num,
            "bit": packet.bit
        })
        print(event.to_json())
        
        # Send ACK
        ack_packet = Packet(packet.seq_num, packet.bit)
        try:
            result = self.subnet2.send_packet(ack_packet)
            if hasattr(result, '__iter__') and hasattr(result, '__next__'):
                # It's a generator, yield it
                yield self.env.process(result)
            else:
                # It's not a generator, just continue
                pass
        except Exception as e:
            # If there's an error, just continue
            pass


class Simulation:
    """Main simulation class"""
    def __init__(self, total_packets, seed, timeout, sender_delay, receiver_delay, channel_delay, simulate_time):
        self.total_packets = total_packets
        self.seed = seed
        self.timeout = timeout
        self.sender_delay = sender_delay
        self.receiver_delay = receiver_delay
        self.channel_delay = channel_delay
        self.simulate_time = simulate_time
        
        # Create environment
        self.env = simpy.Environment()
        
        # Create subnets
        self.subnet1 = Subnet(self.env, "subnet1", seed, channel_delay, "forward")
        self.subnet2 = Subnet(self.env, "subnet2", seed, channel_delay, "backward")
        
        # Create entities
        self.sender = Sender(self.env, total_packets, seed, timeout, sender_delay, self.subnet1)
        self.receiver = Receiver(self.env, receiver_delay, self.subnet2)
        
        # Connect subnets to entities
        self.subnet1.receiver = self.receiver
        self.subnet2.sender = self.sender
        
    def run(self):
        """Run the simulation"""
        # Start sender
        self.env.process(self.sender.send_packet())
        
        # Run simulation
        self.env.run(until=self.simulate_time)


def main():
    """Main function to parse arguments and run simulation"""
    parser = argparse.ArgumentParser(description='Reliable Data Transfer with Deterministic Noise Interference')
    parser.add_argument('--total_packets', type=int, required=True, help='Total number of packets to send')
    parser.add_argument('--seed', type=int, default=42, help='Seed for noise generator')
    parser.add_argument('--timeout', type=int, default=20, help='Sender timeout duration in ms')
    parser.add_argument('--sender_delay', type=int, default=10, help='Sender preparation delay in ms')
    parser.add_argument('--receiver_delay', type=int, default=10, help='Receiver processing delay in ms')
    parser.add_argument('--channel_delay', type=int, default=3, help='Subnet transmission delay in ms')
    parser.add_argument('--simulate_time', type=int, default=1000, help='Total simulation time in ms')
    
    args = parser.parse_args()
    
    # Create and run simulation
    sim = Simulation(
        args.total_packets,
        args.seed,
        args.timeout,
        args.sender_delay,
        args.receiver_delay,
        args.channel_delay,
        args.simulate_time
    )
    
    sim.run()


if __name__ == "__main__":
    main()