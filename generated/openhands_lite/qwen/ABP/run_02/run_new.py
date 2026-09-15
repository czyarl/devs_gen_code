#!/usr/bin/env python3
"""
Reliable Data Transfer Simulation with Deterministic Noise Interference
Using Discrete Event Simulation (DES) with SimPy
"""

import argparse
import json
import simpy

class Packet:
    """Represents a data packet with sequence number and control bit"""
    def __init__(self, seq_num: int, bit: int):
        self.seq_num = seq_num
        self.bit = bit

class ACKPacket:
    """Represents an acknowledgment packet"""
    def __init__(self, ack_bit: int):
        self.ack_bit = ack_bit

class Subnet:
    """Represents a unidirectional transmission channel with deterministic noise"""
    
    def __init__(self, env, name, channel_delay, seed):
        self.env = env
        self.name = name
        self.channel_delay = channel_delay
        self.seed = seed
        self.noise_level = seed  # Initialize noise level with seed
        self.receivers = []
        
    def add_receiver(self, receiver):
        """Add a receiver to this subnet"""
        self.receivers.append(receiver)
        
    def send_packet(self, packet):
        """Send a packet through this subnet with noise simulation"""
        # Determine packet fate based on noise level
        new_noise_level = (17 * self.noise_level + 11) % 100
        behavior = "drop" if new_noise_level < 10 else "pass"
        noise_value = new_noise_level
        
        # Update noise level for next packet
        self.noise_level = new_noise_level
        
        # Report packet fate
        event_data = {
            "time": self.env.now,
            "entity": "subnet",
            "event": "packet_get",
            "payload": {
                "behavior": behavior,
                "channel": "forward" if self.name == "subnet1" else "backward",
                "noise_value": noise_value
            }
        }
        print(json.dumps(event_data))
        
        # If packet is dropped, don't transmit it
        if behavior == "drop":
            return
            
        # Otherwise, wait for channel delay and then transmit to all receivers
        yield self.env.timeout(self.channel_delay)
        
        # Pass packet to all receivers
        for receiver in self.receivers:
            if hasattr(receiver, 'receive_packet'):
                receiver.receive_packet(packet)

class Sender:
    """Sender entity that sends packets with Alternating Bit Protocol"""
    
    def __init__(self, env, total_packets, sender_delay, timeout, subnet1):
        self.env = env
        self.total_packets = total_packets
        self.sender_delay = sender_delay
        self.timeout = timeout
        self.subnet1 = subnet1
        self.seq_num = 1
        self.bit = 0  # Start with bit 0
        self.packet_sent = False
        self.sent_packet = None
        self.retransmissions = 0
        self.ack_received = False
        self.ack_bit = None
        self.timer = None
        
        # Start the sender process
        self.env.process(self._run())
        
    def _run(self):
        """Main sender process"""
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
            
            # Send packet
            event_data = {
                "time": self.env.now,
                "entity": "sender",
                "event": "packet_sent",
                "payload": {
                    "seq_num": packet.seq_num,
                    "bit": packet.bit,
                    "is_retry": self.packet_sent  # True if this is a retransmission
                }
            }
            print(json.dumps(event_data))
            
            # Send packet through subnet1
            self.subnet1.send_packet(packet)
            
            # Start timer
            self.timer = self.env.timeout(self.timeout)
            self.packet_sent = True
            self.sent_packet = packet
            
            # Wait for either ACK or timeout
            try:
                yield self.timer
                # Timeout occurred - retransmit
                self.retransmissions += 1
                self.bit = packet.bit  # Keep same bit for retransmission
                continue  # Go back to sending the same packet
            except simpy.Interrupt:
                # ACK received - continue to next packet
                pass
            
            # Move to next packet
            self.seq_num += 1
            self.bit = 1 - self.bit  # Alternate bit
            
    def receive_ack(self, ack):
        """Receive an acknowledgment"""
        if self.packet_sent and self.sent_packet:
            # Check if ACK is valid
            is_valid = (ack.ack_bit == self.sent_packet.bit)
            
            # Report ACK reception
            event_data = {
                "time": self.env.now,
                "entity": "sender",
                "event": "ack_received",
                "payload": {
                    "ack_bit": ack.ack_bit,
                    "is_valid": is_valid
                }
            }
            print(json.dumps(event_data))
            
            # Cancel timer if valid ACK
            if is_valid:
                if self.timer:
                    self.timer.interrupt()
                self.packet_sent = False
                self.sent_packet = None
            else:
                # Invalid ACK - retransmit
                self.bit = self.sent_packet.bit  # Keep same bit for retransmission

class Receiver:
    """Receiver entity that processes packets and sends ACKs"""
    
    def __init__(self, env, receiver_delay, subnet2):
        self.env = env
        self.receiver_delay = receiver_delay
        self.subnet2 = subnet2
        self.processing = env.process(self._run())
        
    def _run(self):
        """Main receiver process - this is a placeholder"""
        # This process will be interrupted when packets arrive
        while True:
            yield self.env.timeout(1000)  # Placeholder
            
    def receive_packet(self, packet):
        """Receive a packet and send ACK"""
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
        
        # Send ACK
        ack = ACKPacket(packet.bit)
        self.subnet2.send_packet(ack)
        
        # Report ACK sent
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
    """Main simulation function"""
    parser = argparse.ArgumentParser(description='Reliable Data Transfer Simulation')
    parser.add_argument('--total_packets', type=int, default=10, help='Total number of packets to send')
    parser.add_argument('--seed', type=int, default=42, help='Seed for noise generator')
    parser.add_argument('--timeout', type=int, default=20, help='Sender timeout in ms')
    parser.add_argument('--sender_delay', type=int, default=10, help='Sender preparation delay in ms')
    parser.add_argument('--receiver_delay', type=int, default=10, help='Receiver processing delay in ms')
    parser.add_argument('--channel_delay', type=int, default=3, help='Subnet transmission delay in ms')
    parser.add_argument('--simulate_time', type=int, default=1000, help='Total simulation time in ms')
    
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create subnets
    subnet1 = Subnet(env, "subnet1", args.channel_delay, args.seed)
    subnet2 = Subnet(env, "subnet2", args.channel_delay, args.seed)
    
    # Create sender and receiver
    sender = Sender(env, args.total_packets, args.sender_delay, args.timeout, subnet1)
    receiver = Receiver(env, args.receiver_delay, subnet2)
    
    # Connect components to subnets
    subnet1.add_receiver(receiver)
    
    # Run simulation
    env.run(until=args.simulate_time)
    
    # Print final statistics
    print(json.dumps({
        "time": args.simulate_time,
        "entity": "system",
        "event": "simulation_end",
        "payload": {
            "total_packets": args.total_packets,
            "retransmissions": sender.retransmissions
        }
    }))

if __name__ == "__main__":
    main()