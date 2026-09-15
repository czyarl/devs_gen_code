#!/usr/bin/env python3
"""
Alternating Bit Protocol (ABP) Simulation Implementation
"""

import argparse
import sys
import json
import logging
import simpy

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Sender:
    def __init__(self, env, delay, timeout):
        self.env = env
        self.delay = delay
        self.timeout = timeout
        self.subnet = None
        self.seq_num = 0
        self.bit = 0
        self.packet_sent = False
        self.retransmit_count = 0
        self.current_packet = None
        self.ack_received = False
        
    def connect_to(self, subnet):
        self.subnet = subnet
        
    def start(self, total_packets):
        """Start sending packets"""
        while self.seq_num < total_packets:
            # Prepare packet
            yield self.env.timeout(self.delay)
            
            # Emit delay_start event
            print(json.dumps({
                "time": self.env.now,
                "entity": "sender",
                "event": "delay_start",
                "payload": {"type": "preparation", "duration": self.delay}
            }))
            
            # Increment sequence number and bit
            self.seq_num += 1
            self.bit = 1 - self.bit  # Alternate bit
            
            # Create packet
            self.current_packet = {
                "seq_num": self.seq_num,
                "bit": self.bit,
                "is_retry": self.retransmit_count > 0
            }
            
            # Emit packet_sent event
            print(json.dumps({
                "time": self.env.now,
                "entity": "sender",
                "event": "packet_sent",
                "payload": self.current_packet
            }))
            
            # Send packet to subnet
            self.subnet.receive_packet(self.current_packet)
            
            # Start timer
            timer_event = self.env.timeout(self.timeout)
            self.packet_sent = True
            self.ack_received = False
            
            # Wait for ACK or timeout
            # Create an event to signal when we receive an ACK
            ack_event = self.env.event()
            
            # Store the event for later use
            self.ack_event = ack_event
            
            # Wait for either timeout or ACK
            result = yield timer_event | ack_event
            
            # Check which event occurred
            if timer_event in result:
                # Timeout occurred, retransmit
                print(json.dumps({
                    "time": self.env.now,
                    "entity": "sender",
                    "event": "timeout",
                    "payload": {"seq_num": self.seq_num, "bit": self.bit}
                }))
                self.retransmit_count += 1
                # Restart the process for the same packet
                continue
            else:
                # ACK received, continue to next packet
                pass
                
    def receive_ack(self, ack_bit, is_valid):
        """Receive ACK from receiver"""
        # Emit ack_received event
        print(json.dumps({
            "time": self.env.now,
            "entity": "sender",
            "event": "ack_received",
            "payload": {"ack_bit": ack_bit, "is_valid": is_valid}
        }))
        
        # If valid ACK, signal that we received it
        if is_valid:
            self.packet_sent = False  # Reset packet sent flag
            # Signal that we received an ACK
            if hasattr(self, 'ack_event'):
                self.ack_event.succeed()
        else:
            # Invalid ACK, retransmit
            self.packet_sent = True  # Keep waiting for valid ACK
            self.retransmit_count += 1

class Receiver:
    def __init__(self, env, delay):
        self.env = env
        self.delay = delay
        self.subnet = None
        self.packet_queue = simpy.Store(env)
        
    def connect_to(self, subnet):
        self.subnet = subnet
        
    def start(self):
        """Start receiving packets"""
        while True:
            # Wait for packet
            packet = yield self.packet_queue.get()
            
            # Process packet
            yield self.env.timeout(self.delay)
            
            # Emit delay_start event
            print(json.dumps({
                "time": self.env.now,
                "entity": "receiver",
                "event": "delay_start",
                "payload": {"type": "processing", "duration": self.delay}
            }))
            
            # Emit packet_received event
            print(json.dumps({
                "time": self.env.now,
                "entity": "receiver",
                "event": "packet_received",
                "payload": {
                    "seq_num": packet["seq_num"],
                    "bit": packet["bit"]
                }
            }))
            
            # Send ACK back
            ack_packet = {
                "seq_num": packet["seq_num"],
                "bit": packet["bit"]
            }
            
            # Send ACK to subnet
            self.subnet.send_ack(ack_packet)

class Subnet:
    def __init__(self, env, delay, seed, direction):
        self.env = env
        self.delay = delay
        self.seed = seed
        self.direction = direction  # "forward" or "backward"
        self.noise_level = seed
        self.sender = None
        self.receiver = None
        self.packet_queue = simpy.Store(env)
        
    def connect_to(self, component):
        """Connect to either sender or receiver"""
        if isinstance(component, Sender):
            self.sender = component
        elif isinstance(component, Receiver):
            self.receiver = component
            
    def receive_packet(self, packet):
        """Receive packet from sender"""
        # Determine packet fate
        new_noise_level = (17 * self.noise_level + 11) % 100
        self.noise_level = new_noise_level
        
        # Emit packet_get event
        print(json.dumps({
            "time": self.env.now,
            "entity": "subnet",
            "event": "packet_get",
            "payload": {
                "behavior": "drop" if new_noise_level < 10 else "pass",
                "channel": self.direction,
                "noise_value": new_noise_level
            }
        }))
        
        if new_noise_level >= 10:
            # Packet passes through
            # Add delay
            self.env.process(self.transmit_packet(packet))
        else:
            # Packet dropped - no need to send anything
            pass
            
    def transmit_packet(self, packet):
        """Transmit packet after delay"""
        yield self.env.timeout(self.delay)
        # Send to receiver
        if self.receiver:
            self.receiver.packet_queue.put(packet)
            
    def send_ack(self, ack_packet):
        """Send ACK packet"""
        # Determine packet fate
        new_noise_level = (17 * self.noise_level + 11) % 100
        self.noise_level = new_noise_level
        
        # Emit packet_get event
        print(json.dumps({
            "time": self.env.now,
            "entity": "subnet",
            "event": "packet_get",
            "payload": {
                "behavior": "drop" if new_noise_level < 10 else "pass",
                "channel": self.direction,
                "noise_value": new_noise_level
            }
        }))
        
        if new_noise_level >= 10:
            # Packet passes through
            # Add delay
            self.env.process(self.transmit_ack(ack_packet))
        else:
            # Packet dropped - no need to send anything
            pass
            
    def transmit_ack(self, ack_packet):
        """Transmit ACK after delay"""
        yield self.env.timeout(self.delay)
        # Send to sender
        if self.sender:
            # Validate ACK
            is_valid = ack_packet["bit"] == self.sender.current_packet["bit"] if self.sender.current_packet else False
            self.sender.receive_ack(ack_packet["bit"], is_valid)

def main():
    parser = argparse.ArgumentParser(description='ABP Simulation')
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
    
    # Create components
    sender = Sender(env, args.sender_delay, args.timeout)
    receiver = Receiver(env, args.receiver_delay)
    subnet1 = Subnet(env, args.channel_delay, args.seed, "forward")
    subnet2 = Subnet(env, args.channel_delay, args.seed, "backward")
    
    # Connect components
    sender.connect_to(subnet1)
    subnet1.connect_to(receiver)
    receiver.connect_to(subnet2)
    subnet2.connect_to(sender)
    
    # Start the receiver process
    env.process(receiver.start())
    
    # Start simulation
    env.process(sender.start(args.total_packets))
    env.run(until=args.simulate_time)
    
    # Print final statistics
    print(json.dumps({"time": env.now, "entity": "system", "event": "simulation_end", "payload": {}}))

if __name__ == "__main__":
    main()