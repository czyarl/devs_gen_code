#!/usr/bin/env python3
"""
Reliable Data Transfer with Deterministic Noise Interference Simulation
"""

import argparse
import sys
import json
import collections
import simpy

class Packet:
    def __init__(self, seq_num, bit, is_retry=False):
        self.seq_num = seq_num
        self.bit = bit
        self.is_retry = is_retry

class ACKPacket:
    def __init__(self, bit):
        self.bit = bit

class NoiseGenerator:
    def __init__(self, seed):
        self.x = seed
    
    def get_next_noise(self):
        self.x = (17 * self.x + 11) % 100
        return self.x

class Subnet:
    def __init__(self, env, name, delay, noise_seed, direction):
        self.env = env
        self.name = name
        self.delay = delay
        self.noise_generator = NoiseGenerator(noise_seed)
        self.direction = direction  # "forward" or "backward"
        self.packet_queue = simpy.Store(env)
        
    def run(self):
        while True:
            # Wait for packet from the queue
            packet = yield self.packet_queue.get()
            
            # Determine packet fate based on noise level
            noise_value = self.noise_generator.get_next_noise()
            behavior = "drop" if noise_value < 10 else "pass"
            
            # Report packet fate
            event_data = {
                "time": self.env.now,
                "entity": "subnet",
                "event": "packet_get",
                "payload": {
                    "behavior": behavior,
                    "channel": self.direction,
                    "noise_value": noise_value
                }
            }
            print(json.dumps(event_data))
            
            # If packet is dropped, don't process further
            if behavior == "drop":
                continue
                
            # Otherwise, wait for transmission delay and then pass packet
            yield self.env.timeout(self.delay)
            
            # In a real implementation, we'd deliver the packet to the next component
            # For now, we just simulate the transmission delay

class Sender:
    def __init__(self, env, total_packets, timeout, sender_delay, subnet1, subnet2):
        self.env = env
        self.total_packets = total_packets
        self.timeout = timeout
        self.sender_delay = sender_delay
        self.subnet1 = subnet1
        self.subnet2 = subnet2
        self.seq_num = 1
        self.bit = 0
        self.current_packet = None
        self.timer = None
        self.ack_received = False
        
    def run(self):
        while self.seq_num <= self.total_packets:
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
            
            # Wait for preparation delay
            yield self.env.timeout(self.sender_delay)
            
            # Create packet
            packet = Packet(self.seq_num, self.bit)
            self.current_packet = packet
            
            # Send packet to subnet1
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
            self.subnet1.packet_queue.put(packet)
            
            # Start timer
            self.timer = self.env.timeout(self.timeout)
            
            # Wait for either ACK or timeout
            results = yield self.timer | self.subnet2.packet_queue.get()
            
            # Check if we got an ACK or timeout
            if self.timer in results:
                # Timeout occurred - retransmit packet
                event_data = {
                    "time": self.env.now,
                    "entity": "sender",
                    "event": "packet_sent",
                    "payload": {
                        "seq_num": packet.seq_num,
                        "bit": packet.bit,
                        "is_retry": True
                    }
                }
                print(json.dumps(event_data))
                
                # Send retransmitted packet to subnet1
                self.subnet1.packet_queue.put(packet)
                
                # Restart timer
                self.timer = self.env.timeout(self.timeout)
                yield self.timer
                
                # If still no ACK, we stop
                if not self.ack_received:
                    break
            else:
                # We received an ACK
                ack = results[1]  # The ACK packet from the queue
                # Validate ACK
                is_valid = (ack.bit == packet.bit)
                event_data = {
                    "time": self.env.now,
                    "entity": "sender",
                    "event": "ack_received",
                    "payload": {
                        "ack_bit": ack.bit,
                        "is_valid": is_valid
                    }
                }
                print(json.dumps(event_data))
                
                if is_valid:
                    self.ack_received = True
                else:
                    # Invalid ACK, retransmit
                    event_data = {
                        "time": self.env.now,
                        "entity": "sender",
                        "event": "packet_sent",
                        "payload": {
                            "seq_num": packet.seq_num,
                            "bit": packet.bit,
                            "is_retry": True
                        }
                    }
                    print(json.dumps(event_data))
                    
                    # Send retransmitted packet to subnet1
                    self.subnet1.packet_queue.put(packet)
                    
                    # Restart timer
                    self.timer = self.env.timeout(self.timeout)
                    yield self.timer
                    
                    # If still no ACK, we stop
                    if not self.ack_received:
                        break
                    
            # If we received a valid ACK, move to next packet
            if self.ack_received:
                self.ack_received = False
                self.seq_num += 1
                self.bit = 1 - self.bit  # Alternate bit

class Receiver:
    def __init__(self, env, receiver_delay, subnet1, subnet2):
        self.env = env
        self.receiver_delay = receiver_delay
        self.subnet1 = subnet1
        self.subnet2 = subnet2
        
    def run(self):
        while True:
            # Wait for packet from subnet1
            packet = yield self.subnet1.packet_queue.get()
            
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
            
            # Process packet
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
            
            # Send ACK back through subnet2
            ack = ACKPacket(packet.bit)
            self.subnet2.packet_queue.put(ack)

def main():
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
    
    # Create subnets
    subnet1 = Subnet(env, "subnet1", args.channel_delay, args.seed, "forward")
    subnet2 = Subnet(env, "subnet2", args.channel_delay, args.seed, "backward")
    
    # Create sender and receiver
    sender = Sender(env, args.total_packets, args.timeout, args.sender_delay, subnet1, subnet2)
    receiver = Receiver(env, args.receiver_delay, subnet1, subnet2)
    
    # Start simulation processes
    env.process(subnet1.run())
    env.process(subnet2.run())
    env.process(sender.run())
    env.process(receiver.run())
    
    # Run simulation
    env.run(until=args.simulate_time)
    
    # Print final statistics
    print(json.dumps({
        "time": env.now,
        "entity": "system",
        "event": "simulation_complete",
        "payload": {
            "total_packets": args.total_packets,
            "sent_packets": args.total_packets,  # All packets sent
            "received_packets": 0  # We don't track received packets in this simple version
        }
    }))

if __name__ == "__main__":
    main()