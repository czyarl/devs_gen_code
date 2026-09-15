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
    """Handles logging events to stdout in JSONL format."""
    
    def __init__(self):
        self.logger = logging.getLogger('abp')
        self.logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter('%(message)s'))
        self.logger.addHandler(handler)
    
    def log_event(self, time, entity, event, payload):
        """Log an event in the required JSONL format."""
        record = {
            "time": float(time),
            "entity": entity,
            "event": event,
            "payload": payload
        }
        self.logger.info(json.dumps(record))


class Subnet:
    """Represents a transmission channel with deterministic noise."""
    
    def __init__(self, env, name, channel_type, seed, channel_delay, logger):
        """
        Initialize subnet.
        
        Args:
            env: SimPy environment
            name: Subnet identifier
            channel_type: "forward" or "backward"
            seed: Initial noise seed
            channel_delay: Transmission delay in ms
            logger: EventLogger instance
        """
        self.env = env
        self.name = name
        self.channel_type = channel_type
        self.noise_level = seed
        self.channel_delay = channel_delay
        self.logger = logger
        self.store = simpy.Store(env)
        self.env.process(self.run())
    
    def run(self):
        """Process packets through the subnet."""
        while True:
            packet = yield self.store.get()
            
            # Calculate noise level and determine packet fate
            x_new = (17 * self.noise_level + 11) % 100
            noise_value = x_new
            
            # Determine if packet is dropped
            if x_new < 10:
                behavior = "drop"
                # Packet is dropped, don't forward it
                self.logger.log_event(
                    self.env.now,
                    "subnet",
                    "packet_get",
                    {
                        "behavior": "drop",
                        "channel": self.channel_type,
                        "noise_value": noise_value
                    }
                )
            else:
                behavior = "pass"
                self.logger.log_event(
                    self.env.now,
                    "subnet",
                    "packet_get",
                    {
                        "behavior": "pass",
                        "channel": self.channel_type,
                        "noise_value": noise_value
                    }
                )
                # Wait for channel delay
                yield self.env.timeout(self.channel_delay)
                # Forward the packet
                packet['destination'].receive(packet)
            
            # Update noise level for next packet
            self.noise_level = x_new
    
    def send(self, packet):
        """Send a packet through the subnet."""
        self.store.put(packet)


class Receiver:
    """Receives packets and sends ACKs."""
    
    def __init__(self, env, subnet_backward, receiver_delay, logger):
        """
        Initialize receiver.
        
        Args:
            env: SimPy environment
            subnet_backward: Subnet for sending ACKs
            receiver_delay: Processing delay in ms
            logger: EventLogger instance
        """
        self.env = env
        self.subnet_backward = subnet_backward
        self.receiver_delay = receiver_delay
        self.logger = logger
        self.buffer = None  # Buffer with capacity 1
        self.busy = False
        self.store = simpy.Store(env)
        self.env.process(self.run())
    
    def receive(self, packet):
        """Receive a packet from the forward subnet."""
        if not self.busy:
            # Buffer is empty, store the packet
            self.buffer = packet
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
                {
                    "type": "processing",
                    "duration": float(self.receiver_delay)
                }
            )
            
            # Wait for processing delay
            yield self.env.timeout(self.receiver_delay)
            
            # Packet successfully received
            self.logger.log_event(
                self.env.now,
                "receiver",
                "packet_received",
                {
                    "seq_num": packet['seq_num'],
                    "bit": packet['bit']
                }
            )
            
            # Send ACK
            ack_packet = {
                'type': 'ack',
                'ack_bit': packet['bit'],
                'destination': None  # Will be set by sender
            }
            self.subnet_backward.send(ack_packet)
            
            # Clear buffer and mark as not busy
            self.buffer = None
            self.busy = False


class Sender:
    """Sends packets using Alternating Bit Protocol."""
    
    def __init__(self, env, subnet_forward, subnet_backward, total_packets, 
                 timeout, sender_delay, logger):
        """
        Initialize sender.
        
        Args:
            env: SimPy environment
            subnet_forward: Subnet for sending data packets
            subnet_backward: Subnet for receiving ACKs
            total_packets: Total number of packets to send
            timeout: Timeout duration in ms
            sender_delay: Preparation delay in ms
            logger: EventLogger instance
        """
        self.env = env
        self.subnet_forward = subnet_forward
        self.subnet_backward = subnet_backward
        self.total_packets = total_packets
        self.timeout = timeout
        self.sender_delay = sender_delay
        self.logger = logger
        
        self.current_seq = 1
        self.current_bit = 0  # First bit is 0
        self.packets_sent = 0
        self.waiting_for_ack = False
        self.current_packet = None
        self.timer_process = None
        self.ack_store = simpy.Store(env)
        
        # Set receiver as destination for ACKs
        subnet_backward.receiver = self
        
        self.env.process(self.run())
    
    def receive(self, packet):
        """Receive an ACK from the backward subnet."""
        self.ack_store.put(packet)
    
    def run(self):
        """Main sender process."""
        while self.packets_sent < self.total_packets:
            # Start preparation delay
            self.logger.log_event(
                self.env.now,
                "sender",
                "delay_start",
                {
                    "type": "preparation",
                    "duration": float(self.sender_delay)
                }
            )
            
            # Wait for preparation delay
            yield self.env.timeout(self.sender_delay)
            
            # Create and send packet
            is_retry = False
            packet = {
                'type': 'data',
                'seq_num': self.current_seq,
                'bit': self.current_bit,
                'destination': None  # Will be set by receiver
            }
            self.current_packet = packet
            
            self.logger.log_event(
                self.env.now,
                "sender",
                "packet_sent",
                {
                    "seq_num": self.current_seq,
                    "bit": self.current_bit,
                    "is_retry": is_retry
                }
            )
            
            self.subnet_forward.send(packet)
            self.waiting_for_ack = True
            
            # Start timer
            self.timer_process = self.env.process(self.timer())
            
            # Wait for ACK
            while self.waiting_for_ack:
                ack_packet = yield self.ack_store.get()
                
                # Check if ACK is valid
                is_valid = (ack_packet['ack_bit'] == self.current_bit)
                
                self.logger.log_event(
                    self.env.now,
                    "sender",
                    "ack_received",
                    {
                        "ack_bit": ack_packet['ack_bit'],
                        "is_valid": is_valid
                    }
                )
                
                if is_valid:
                    # Valid ACK received
                    self.waiting_for_ack = False
                    if self.timer_process.is_alive:
                        self.timer_process.interrupt()
                    
                    # Move to next packet
                    self.packets_sent += 1
                    self.current_seq += 1
                    self.current_bit = 1 - self.current_bit  # Toggle bit
    
    def timer(self):
        """Timeout timer for retransmission."""
        try:
            yield self.env.timeout(self.timeout)
            # Timer expired, retransmit
            self.retransmit()
        except simpy.Interrupt:
            # ACK received, timer interrupted
            pass
    
    def retransmit(self):
        """Retransmit the current packet."""
        if self.waiting_for_ack and self.current_packet:
            is_retry = True
            
            self.logger.log_event(
                self.env.now,
                "sender",
                "packet_sent",
                {
                    "seq_num": self.current_packet['seq_num'],
                    "bit": self.current_packet['bit'],
                    "is_retry": is_retry
                }
            )
            
            self.subnet_forward.send(self.current_packet)
            
            # Restart timer
            self.timer_process = self.env.process(self.timer())


def main():
    """Main entry point for the simulation."""
    parser = argparse.ArgumentParser(
        description='Alternating Bit Protocol Simulation with Deterministic Noise'
    )
    
    parser.add_argument(
        '--total_packets',
        type=int,
        required=True,
        help='Total number of packets to send'
    )
    
    parser.add_argument(
        '--seed',
        type=int,
        default=42,
        help='Initialization seed for noise generator (default: 42)'
    )
    
    parser.add_argument(
        '--timeout',
        type=int,
        default=20,
        help='Sender timeout duration in ms (default: 20)'
    )
    
    parser.add_argument(
        '--sender_delay',
        type=int,
        default=10,
        help='Sender preparation delay in ms (default: 10)'
    )
    
    parser.add_argument(
        '--receiver_delay',
        type=int,
        default=10,
        help='Receiver processing delay in ms (default: 10)'
    )
    
    parser.add_argument(
        '--channel_delay',
        type=int,
        default=3,
        help='Subnet transmission delay in ms (default: 3)'
    )
    
    parser.add_argument(
        '--simulate_time',
        type=int,
        default=1000,
        help='Total simulation time in ms (default: 1000)'
    )
    
    args = parser.parse_args()
    
    # Create SimPy environment
    env = simpy.Environment()
    
    # Create event logger
    logger = EventLogger()
    
    # Create subnets
    subnet_forward = Subnet(
        env,
        'subnet1',
        'forward',
        args.seed,
        args.channel_delay,
        logger
    )
    
    subnet_backward = Subnet(
        env,
        'subnet2',
        'backward',
        args.seed,
        args.channel_delay,
        logger
    )
    
    # Create receiver
    receiver = Receiver(
        env,
        subnet_backward,
        args.receiver_delay,
        logger
    )
    
    # Set receiver as destination for forward subnet
    subnet_forward.receiver = receiver
    
    # Create sender
    sender = Sender(
        env,
        subnet_forward,
        subnet_backward,
        args.total_packets,
        args.timeout,
        args.sender_delay,
        logger
    )
    
    # Run simulation
    env.run(until=args.simulate_time)


if __name__ == '__main__':
    main()
