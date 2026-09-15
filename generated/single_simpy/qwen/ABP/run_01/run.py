import argparse
import sys
import json
import logging
import random
import simpy
from collections import deque

# Configure logging to stderr
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class Packet:
    def __init__(self, seq_num, bit):
        self.seq_num = seq_num
        self.bit = bit

class ACKPacket:
    def __init__(self, bit):
        self.bit = bit

class Sender:
    def __init__(self, env, total_packets, sender_delay, timeout, subnet1, receiver):
        self.env = env
        self.total_packets = total_packets
        self.sender_delay = sender_delay
        self.timeout = timeout
        self.subnet1 = subnet1
        self.receiver = receiver
        self.current_seq = 1
        self.current_bit = 0
        self.timer = None
        self.is_waiting_for_ack = False
        self.retransmission_count = 0
        self.packet_buffer = deque()
        self.sent_packets = {}
        
    def run(self):
        while self.current_seq <= self.total_packets:
            # Preparation delay
            yield self.env.timeout(self.sender_delay)
            self.log_event("delay_start", {"type": "preparation", "duration": self.sender_delay})
            
            # Create packet
            packet = Packet(self.current_seq, self.current_bit)
            self.sent_packets[self.current_seq] = packet
            
            # Send packet
            self.log_event("packet_sent", {"seq_num": self.current_seq, "bit": self.current_bit, "is_retry": self.retransmission_count > 0})
            self.subnet1.send_packet(packet)
            
            # Start timer
            self.timer = self.env.timeout(self.timeout)
            self.is_waiting_for_ack = True
            self.retransmission_count = 0
            
            # Wait for ACK or timeout
            yield self.timer | self.env.event()
            
            # Check if timeout occurred
            if self.timer not in self.env.active_process.events:
                # Timeout occurred
                self.log_event("timeout", {"seq_num": self.current_seq, "bit": self.current_bit})
                self.retransmission_count += 1
                # Retransmit
                self.subnet1.send_packet(packet)
                self.timer = self.env.timeout(self.timeout)
                yield self.timer | self.env.event()
                if self.timer not in self.env.active_process.events:
                    # Timeout again, but we stop here
                    break
            else:
                # Got ACK
                pass
            
            # Move to next packet
            self.current_seq += 1
            self.current_bit = 1 - self.current_bit  # Toggle bit
            self.is_waiting_for_ack = False
            
        # Simulation done
        self.log_event("sender_done", {})
        
    def receive_ack(self, ack):
        if self.is_waiting_for_ack:
            if ack.bit == self.sent_packets[self.current_seq].bit:
                self.log_event("ack_received", {"ack_bit": ack.bit, "is_valid": True})
                self.is_waiting_for_ack = False
                self.timer.cancel()
            else:
                self.log_event("ack_received", {"ack_bit": ack.bit, "is_valid": False})
                # Invalid ACK, do nothing, wait for timeout or retransmission
                
    def log_event(self, event, payload):
        event_data = {
            "time": self.env.now,
            "entity": "sender",
            "event": event,
            "payload": payload
        }
        print(json.dumps(event_data))

class Receiver:
    def __init__(self, env, receiver_delay, subnet2, sender):
        self.env = env
        self.receiver_delay = receiver_delay
        self.subnet2 = subnet2
        self.sender = sender
        self.buffer = None
        self.processing = False
        
    def run(self):
        while True:
            # Wait for packet
            packet = yield self.subnet2.packet_received
            # Processing delay
            yield self.env.timeout(self.receiver_delay)
            self.log_event("delay_start", {"type": "processing", "duration": self.receiver_delay})
            
            # Process packet
            self.log_event("packet_received", {"seq_num": packet.seq_num, "bit": packet.bit})
            
            # Send ACK
            ack = ACKPacket(packet.bit)
            self.subnet2.send_packet(ack)
            
    def log_event(self, event, payload):
        event_data = {
            "time": self.env.now,
            "entity": "receiver",
            "event": event,
            "payload": payload
        }
        print(json.dumps(event_data))

class Subnet:
    def __init__(self, env, channel_delay, seed, name):
        self.env = env
        self.channel_delay = channel_delay
        self.seed = seed
        self.name = name
        self.noise_level = seed
        self.packet_received = simpy.Store(env)
        self.packet_buffer = deque()
        self.is_busy = False
        
    def run(self):
        while True:
            # Wait for packet
            packet = yield self.packet_received.get()
            
            # Determine fate based on noise level
            new_noise = (17 * self.noise_level + 11) % 100
            self.noise_level = new_noise
            
            self.log_event("packet_get", {
                "behavior": "drop" if new_noise < 10 else "pass",
                "channel": "forward" if self.name == "subnet1" else "backward",
                "noise_value": new_noise
            })
            
            if new_noise >= 10:
                # Pass packet after delay
                yield self.env.timeout(self.channel_delay)
                # Send to next component
                if self.name == "subnet1":
                    self.packet_received.put(packet)
                else:
                    self.packet_received.put(packet)
            else:
                # Drop packet
                pass
                
    def send_packet(self, packet):
        self.packet_received.put(packet)
        
    def log_event(self, event, payload):
        event_data = {
            "time": self.env.now,
            "entity": "subnet",
            "event": event,
            "payload": payload
        }
        print(json.dumps(event_data))

def main():
    parser = argparse.ArgumentParser(description='Reliable Data Transfer Simulation')
    parser.add_argument('--total_packets', type=int, required=True, help='Total number of packets to send')
    parser.add_argument('--seed', type=int, default=42, help='Seed for noise generator')
    parser.add_argument('--timeout', type=int, default=20, help='Sender timeout in ms')
    parser.add_argument('--sender_delay', type=int, default=10, help='Sender preparation delay in ms')
    parser.add_argument('--receiver_delay', type=int, default=10, help='Receiver processing delay in ms')
    parser.add_argument('--channel_delay', type=int, default=3, help='Subnet transmission delay in ms')
    parser.add_argument('--simulate_time', type=int, default=1000, help='Total simulation time in ms')
    
    args = parser.parse_args()
    
    # Initialize simulation environment
    env = simpy.Environment()
    
    # Create components
    subnet1 = Subnet(env, args.channel_delay, args.seed, "subnet1")
    subnet2 = Subnet(env, args.channel_delay, args.seed, "subnet2")
    
    # Create sender and receiver
    sender = Sender(env, args.total_packets, args.sender_delay, args.timeout, subnet1, None)
    receiver = Receiver(env, args.receiver_delay, subnet2, sender)
    
    # Connect sender to subnet1
    sender.subnet1 = subnet1
    sender.receiver = receiver
    
    # Connect receiver to subnet2
    receiver.subnet2 = subnet2
    
    # Start components
    env.process(sender.run())
    env.process(receiver.run())
    env.process(subnet1.run())
    env.process(subnet2.run())
    
    # Run simulation
    env.run(until=args.simulate_time)

if __name__ == "__main__":
    main()