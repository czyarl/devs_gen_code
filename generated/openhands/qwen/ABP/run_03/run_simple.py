#!/usr/bin/env python3
"""
Simple Reliable Data Transfer Simulation with Deterministic Noise Interference
"""

import argparse
import sys
import json
import simpy


class Packet:
    def __init__(self, seq_num, bit):
        self.seq_num = seq_num
        self.bit = bit


class ACKPacket:
    def __init__(self, ack_bit):
        self.ack_bit = ack_bit


class Subnet:
    def __init__(self, env, channel_delay, seed, channel_name):
        self.env = env
        self.channel_delay = channel_delay
        self.seed = seed
        self.channel_name = channel_name
        self.noise_level = seed
        self.packet_queue = simpy.Store(env)
        
        # Start the simulation process
        self.process = env.process(self._run())
    
    def send_packet(self, packet, direction):
        # Add packet to queue for processing
        self.packet_queue.put(packet)
    
    def _run(self):
        while True:
            # Wait for packet to arrive
            packet = yield self.packet_queue.get()
            
            # Determine packet fate based on noise level
            new_noise_level = (17 * self.noise_level + 11) % 100
            behavior = "drop" if new_noise_level < 10 else "pass"
            
            # Print packet fate event
            event_data = {
                "time": self.env.now,
                "entity": "subnet",
                "event": "packet_get",
                "payload": {
                    "behavior": behavior,
                    "channel": self.channel_name,
                    "noise_value": new_noise_level
                }
            }
            print(json.dumps(event_data))
            
            # Update noise level
            self.noise_level = new_noise_level
            
            # If packet is dropped, don't send it further
            if behavior == "drop":
                continue
            
            # Otherwise, wait for channel delay and then send
            yield self.env.timeout(self.channel_delay)


class Sender:
    def __init__(self, env, total_packets, seed, timeout, sender_delay, channel_delay, subnet1):
        self.env = env
        self.total_packets = total_packets
        self.seed = seed
        self.timeout = timeout
        self.sender_delay = sender_delay
        self.channel_delay = channel_delay
        self.subnet1 = subnet1
        self.seq_num = 1
        self.bit = 0
        
        # Start the simulation process
        self.process = env.process(self._run())
    
    def _run(self):
        while self.seq_num <= self.total_packets:
            # Wait for preparation delay
            yield self.env.timeout(self.sender_delay)
            
            # Print delay start event
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
            
            # Send packet
            packet = Packet(self.seq_num, self.bit)
            
            # Print packet sent event
            event_data = {
                "time": self.env.now,
                "entity": "sender",
                "event": "packet_sent",
                "payload": {
                    "seq_num": packet.seq_num,
                    "bit": packet.bit,
                    "is_retry": False
                }
            }
            print(json.dumps(event_data))
            
            # Send packet to subnet1
            self.subnet1.send_packet(packet, "forward")
            
            # Move to next packet
            self.seq_num += 1
            self.bit = 1 - self.bit  # Alternate bit


class Receiver:
    def __init__(self, env, receiver_delay, channel_delay, subnet2):
        self.env = env
        self.receiver_delay = receiver_delay
        self.channel_delay = channel_delay
        self.subnet2 = subnet2
        
        # Start the simulation process
        self.process = env.process(self._run())
    
    def _run(self):
        while True:
            # Wait for packet to arrive
            packet = yield self.subnet2.packet_queue.get()
            
            # Print delay start event
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
            
            # Start processing delay
            yield self.env.timeout(self.receiver_delay)
            
            # Print packet received event
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
            self.subnet2.send_packet(ack, "backward")
            
            # Print ACK sent event
            event_data = {
                "time": self.env.now,
                "entity": "receiver",
                "event": "ack_sent",
                "payload": {
                    "ack_bit": ack.ack_bit
                }
            }
            print(json.dumps(event_data))


def main():
    parser = argparse.ArgumentParser(description='Reliable Data Transfer Simulation')
    parser.add_argument('--total_packets', type=int, required=True, help='Total number of packets to send')
    parser.add_argument('--seed', type=int, default=42, help='Seed for noise generator')
    parser.add_argument('--timeout', type=int, default=20, help='Sender timeout duration in ms')
    parser.add_argument('--sender_delay', type=int, default=10, help='Sender preparation delay in ms')
    parser.add_argument('--receiver_delay', type=int, default=10, help='Receiver processing delay in ms')
    parser.add_argument('--channel_delay', type=int, default=3, help='Subnet transmission delay in ms')
    parser.add_argument('--simulate_time', type=int, default=1000, help='Total simulation time in ms')
    
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create subnets
    subnet1 = Subnet(env, args.channel_delay, args.seed, "forward")
    subnet2 = Subnet(env, args.channel_delay, args.seed, "backward")
    
    # Create sender and receiver
    sender = Sender(env, args.total_packets, args.seed, args.timeout, args.sender_delay, args.channel_delay, subnet1)
    receiver = Receiver(env, args.receiver_delay, args.channel_delay, subnet2)
    
    # Run simulation
    env.run(until=args.simulate_time)


if __name__ == "__main__":
    main()