#!/usr/bin/env python3
"""
Alternating Bit Protocol (ABP) Simulation with Deterministic Noise
"""

import argparse
import sys
import json
import logging
from collections import deque
import simpy


class EventLogger:
    """Handles logging of simulation events to stdout in JSONL format."""
    
    def __init__(self):
        self.logger = logging.getLogger('abp_simulation')
        self.logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter('%(message)s'))
        self.logger.addHandler(handler)
    
    def log_event(self, time, entity, event, payload):
        """Log an event in JSONL format."""
        event_record = {
            "time": round(time, 2),
            "entity": entity,
            "event": event,
            "payload": payload
        }
        self.logger.info(json.dumps(event_record))


class Subnet:
    """Represents a transmission channel with deterministic noise."""
    
    def __init__(self, env, name, channel_type, seed, channel_delay, logger):
        self.env = env
        self.name = name
        self.channel_type = channel_type  # "forward" or "backward"
        self.noise_level = seed
        self.channel_delay = channel_delay
        self.logger = logger
        self.destination = None  # Will be set after creation
        self.store = simpy.Store(env)
        env.process(self.run())
    
    def run(self):
        """Process packets through the subnet."""
        while True:
            packet = yield self.store.get()
            
            # Calculate noise level and determine packet fate
            x_new = (17 * self.noise_level + 11) % 100
            behavior = "drop" if x_new < 10 else "pass"
            
            # Log packet fate determination
            self.logger.log_event(
                self.env.now,
                "subnet",
                "packet_get",
                {
                    "behavior": behavior,
                    "channel": self.channel_type,
                    "noise_value": x_new
                }
            )
            
            # Update noise level for next packet
            self.noise_level = x_new
            
            # If packet passes, transmit after channel delay
            if behavior == "pass":
                yield self.env.timeout(self.channel_delay)
                if self.destination:
                    self.destination.receive_packet(packet)


class Receiver:
    """Receives packets and sends ACKs."""
    
    def __init__(self, env, receiver_delay, subnet_backward, logger):
        self.env = env
        self.receiver_delay = receiver_delay
        self.subnet_backward = subnet_backward
        self.logger = logger
        self.buffer = None
        self.busy = False
        self.store = simpy.Store(env)
        env.process(self.run())
    
    def receive_packet(self, packet):
        """Receive a packet from the subnet."""
        if not self.busy:
            self.store.put(packet)
        # If busy, packet is dropped (buffer capacity is 1)
    
    def run(self):
        """Process received packets."""
        while True:
            packet = yield self.store.get()
            
            # Start processing delay
            self.busy = True
            self.logger.log_event(
                self.env.now,
                "receiver",
                "delay_start",
                {"type": "processing", "duration": self.receiver_delay}
            )
            
            yield self.env.timeout(self.receiver_delay)
            
            # Packet successfully received
            self.logger.log_event(
                self.env.now,
                "receiver",
                "packet_received",
                {"seq_num": packet['seq_num'], "bit": packet['bit']}
            )
            
            # Send ACK
            ack_packet = {
                'type': 'ack',
                'bit': packet['bit'],
                'destination': packet['sender']
            }
            self.subnet_backward.store.put(ack_packet)
            
            self.busy = False


class Sender:
    """Sends packets using stop-and-wait protocol with timeout."""
    
    def __init__(self, env, total_packets, timeout, sender_delay, subnet_forward, logger):
        self.env = env
        self.total_packets = total_packets
        self.timeout = timeout
        self.sender_delay = sender_delay
        self.subnet_forward = subnet_forward
        self.logger = logger
        self.current_seq = 1
        self.current_bit = 0
        self.packets_sent = 0
        self.waiting_for_ack = False
        self.current_packet = None
        self.timer_process = None
        self.store = simpy.Store(env)
        env.process(self.run())
    
    def receive_packet(self, packet):
        """Receive an ACK from the subnet."""
        if packet['type'] == 'ack':
            self.store.put(packet)
    
    def run(self):
        """Main sender process."""
        while self.packets_sent < self.total_packets:
            # Prepare packet
            self.logger.log_event(
                self.env.now,
                "sender",
                "delay_start",
                {"type": "preparation", "duration": self.sender_delay}
            )
            
            yield self.env.timeout(self.sender_delay)
            
            # Create packet
            packet = {
                'type': 'data',
                'seq_num': self.current_seq,
                'bit': self.current_bit,
                'sender': self,
                'destination': None  # Will be set by subnet
            }
            self.current_packet = packet
            
            # Send packet
            is_retry = self.waiting_for_ack
            self.logger.log_event(
                self.env.now,
                "sender",
                "packet_sent",
                {"seq_num": packet['seq_num'], "bit": packet['bit'], "is_retry": is_retry}
            )
            
            self.subnet_forward.store.put(packet)
            
            # Start timer if not already waiting
            if not self.waiting_for_ack:
                self.waiting_for_ack = True
                self.timer_process = self.env.process(self.timeout_handler())
            
            # Wait for ACK
            ack = yield self.store.get()
            
            # Check if ACK is valid
            is_valid = (ack['bit'] == self.current_bit)
            self.logger.log_event(
                self.env.now,
                "sender",
                "ack_received",
                {"ack_bit": ack['bit'], "is_valid": is_valid}
            )
            
            if is_valid:
                # Valid ACK, move to next packet
                if self.timer_process:
                    self.timer_process.interrupt()
                
                self.packets_sent += 1
                self.current_seq += 1
                self.current_bit = 1 - self.current_bit  # Toggle bit
                self.waiting_for_ack = False
                self.current_packet = None
            # If invalid ACK, continue waiting (will timeout and retry)
    
    def timeout_handler(self):
        """Handle timeout for ACK."""
        try:
            yield self.env.timeout(self.timeout)
            # Timeout expired, retransmit
            if self.current_packet:
                self.logger.log_event(
                    self.env.now,
                    "sender",
                    "delay_start",
                    {"type": "preparation", "duration": self.sender_delay}
                )
                
                yield self.env.timeout(self.sender_delay)
                
                self.logger.log_event(
                    self.env.now,
                    "sender",
                    "packet_sent",
                    {
                        "seq_num": self.current_packet['seq_num'],
                        "bit": self.current_packet['bit'],
                        "is_retry": True
                    }
                )
                
                self.subnet_forward.store.put(self.current_packet.copy())
                
                # Restart timer
                self.timer_process = self.env.process(self.timeout_handler())
        except simpy.Interrupt:
            # ACK received, cancel timeout
            pass


def main():
    """Main simulation entry point."""
    parser = argparse.ArgumentParser(description='Alternating Bit Protocol Simulation')
    parser.add_argument('--total_packets', type=int, required=True,
                        help='Total number of packets to send')
    parser.add_argument('--seed', type=int, default=42,
                        help='Initialization seed for noise generator')
    parser.add_argument('--timeout', type=int, default=20,
                        help='Sender timeout duration in ms')
    parser.add_argument('--sender_delay', type=int, default=10,
                        help='Sender preparation delay in ms')
    parser.add_argument('--receiver_delay', type=int, default=10,
                        help='Receiver processing delay in ms')
    parser.add_argument('--channel_delay', type=int, default=3,
                        help='Subnet transmission delay in ms')
    parser.add_argument('--simulate_time', type=int, default=1000,
                        help='Total simulation time in ms')
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create event logger
    logger = EventLogger()
    
    # Create subnets
    subnet_forward = Subnet(env, "subnet1", "forward", args.seed, args.channel_delay, logger)
    subnet_backward = Subnet(env, "subnet2", "backward", args.seed, args.channel_delay, logger)
    
    # Create receiver
    receiver = Receiver(env, args.receiver_delay, subnet_backward, logger)
    
    # Create sender
    sender = Sender(env, args.total_packets, args.timeout, args.sender_delay, subnet_forward, logger)
    
    # Set destinations
    subnet_forward.destination = receiver
    subnet_backward.destination = sender
    
    # Run simulation
    env.run(until=args.simulate_time)


if __name__ == '__main__':
    main()