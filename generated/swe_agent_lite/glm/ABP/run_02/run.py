#!/usr/bin/env python3
"""
Alternating Bit Protocol (ABP) Simulation with Deterministic Noise Interference
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
        self.logger = logging.getLogger('abp_simulation')
        self.logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter('%(message)s'))
        self.logger.addHandler(handler)
    
    def log_event(self, time, entity, event, payload):
        """Log an event in JSONL format."""
        record = {
            "time": float(time),
            "entity": entity,
            "event": event,
            "payload": payload
        }
        self.logger.info(json.dumps(record))


class Subnet:
    """Represents a transmission channel with deterministic noise."""
    
    def __init__(self, env, name, direction, channel_delay, seed, logger):
        self.env = env
        self.name = name
        self.direction = direction  # "forward" or "backward"
        self.channel_delay = channel_delay
        self.noise_level = seed
        self.logger = logger
        self.input_pipe = simpy.Store(env)
        self.output_pipe = simpy.Store(env)
        self.env.process(self.run())
    
    def run(self):
        """Process packets through the subnet."""
        while True:
            packet = yield self.input_pipe.get()
            
            # Calculate noise level and determine packet fate
            x_new = (17 * self.noise_level + 11) % 100
            
            # Log packet fate determination
            behavior = "drop" if x_new < 10 else "pass"
            self.logger.log_event(
                time=self.env.now,
                entity="subnet",
                event="packet_get",
                payload={
                    "behavior": behavior,
                    "channel": self.direction,
                    "noise_value": x_new
                }
            )
            
            # Update noise level for next packet
            self.noise_level = x_new
            
            # If packet is not dropped, transmit after channel delay
            if x_new >= 10:
                yield self.env.timeout(self.channel_delay)
                yield self.output_pipe.put(packet)


class Sender:
    """Implements the Sender entity with ABP protocol."""
    
    def __init__(self, env, total_packets, timeout, sender_delay, logger, subnet1, subnet2):
        self.env = env
        self.total_packets = total_packets
        self.timeout = timeout
        self.sender_delay = sender_delay
        self.logger = logger
        self.subnet1 = subnet1  # Forward channel
        self.subnet2 = subnet2  # Backward channel (for ACKs)
        
        self.current_seq = 1
        self.current_bit = 0
        self.packets_sent = 0
        self.timer_process = None
        self.waiting_for_ack = False
        
        self.env.process(self.run())
    
    def run(self):
        """Main sender process."""
        while self.packets_sent < self.total_packets:
            # Preparation delay
            self.logger.log_event(
                time=self.env.now,
                entity="sender",
                event="delay_start",
                payload={
                    "type": "preparation",
                    "duration": float(self.sender_delay)
                }
            )
            yield self.env.timeout(self.sender_delay)
            
            # Send packet
            is_retry = self.waiting_for_ack
            packet = {
                "seq_num": self.current_seq,
                "bit": self.current_bit
            }
            
            self.logger.log_event(
                time=self.env.now,
                entity="sender",
                event="packet_sent",
                payload={
                    "seq_num": self.current_seq,
                    "bit": self.current_bit,
                    "is_retry": is_retry
                }
            )
            
            yield self.subnet1.input_pipe.put(packet)
            
            # Start timer and wait for ACK
            self.waiting_for_ack = True
            self.timer_process = self.env.process(self.timeout_timer())
            
            # Wait for ACK
            ack_received = False
            while not ack_received and self.packets_sent < self.total_packets:
                ack = yield self.subnet2.output_pipe.get()
                
                # Check if ACK is valid
                is_valid = (ack["bit"] == self.current_bit)
                
                self.logger.log_event(
                    time=self.env.now,
                    entity="sender",
                    event="ack_received",
                    payload={
                        "ack_bit": ack["bit"],
                        "is_valid": is_valid
                    }
                )
                
                if is_valid:
                    # Valid ACK received
                    ack_received = True
                    self.waiting_for_ack = False
                    if self.timer_process.is_alive:
                        self.timer_process.interrupt()
                    
                    # Move to next packet
                    self.packets_sent += 1
                    self.current_seq += 1
                    self.current_bit = 1 - self.current_bit  # Toggle bit
    
    def timeout_timer(self):
        """Timer for retransmission."""
        try:
            yield self.env.timeout(self.timeout)
            # Timer expired, trigger retransmission
            # The main loop will handle this by sending the same packet again
        except simpy.Interrupt:
            # ACK received, timer cancelled
            pass


class Receiver:
    """Implements the Receiver entity with buffer capacity 1."""
    
    def __init__(self, env, receiver_delay, logger, subnet1, subnet2):
        self.env = env
        self.receiver_delay = receiver_delay
        self.logger = logger
        self.subnet1 = subnet1  # Forward channel (for data packets)
        self.subnet2 = subnet2  # Backward channel (for ACKs)
        
        self.buffer = None
        self.buffer_capacity = 1
        self.is_busy = False
        
        self.env.process(self.run())
    
    def run(self):
        """Main receiver process."""
        while True:
            # Wait for packet from subnet1
            packet = yield self.subnet1.output_pipe.get()
            
            # Check if buffer is available
            if self.buffer is None:
                # Buffer is empty, store packet
                self.buffer = packet
                
                # Start processing delay
                self.logger.log_event(
                    time=self.env.now,
                    entity="receiver",
                    event="delay_start",
                    payload={
                        "type": "processing",
                        "duration": float(self.receiver_delay)
                    }
                )
                
                yield self.env.timeout(self.receiver_delay)
                
                # Process the packet
                self.logger.log_event(
                    time=self.env.now,
                    entity="receiver",
                    event="packet_received",
                    payload={
                        "seq_num": self.buffer["seq_num"],
                        "bit": self.buffer["bit"]
                    }
                )
                
                # Send ACK
                ack = {
                    "bit": self.buffer["bit"]
                }
                yield self.subnet2.input_pipe.put(ack)
                
                # Clear buffer
                self.buffer = None
            else:
                # Buffer is full, packet is dropped (only first one is stored)
                pass


def main():
    """Main entry point for the simulation."""
    parser = argparse.ArgumentParser(
        description='Alternating Bit Protocol (ABP) Simulation with Deterministic Noise'
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
    
    # Create event logger
    logger = EventLogger()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create subnets (channels)
    subnet1 = Subnet(
        env=env,
        name="subnet1",
        direction="forward",
        channel_delay=args.channel_delay,
        seed=args.seed,
        logger=logger
    )
    
    subnet2 = Subnet(
        env=env,
        name="subnet2",
        direction="backward",
        channel_delay=args.channel_delay,
        seed=args.seed,
        logger=logger
    )
    
    # Create sender and receiver
    sender = Sender(
        env=env,
        total_packets=args.total_packets,
        timeout=args.timeout,
        sender_delay=args.sender_delay,
        logger=logger,
        subnet1=subnet1,
        subnet2=subnet2
    )
    
    receiver = Receiver(
        env=env,
        receiver_delay=args.receiver_delay,
        logger=logger,
        subnet1=subnet1,
        subnet2=subnet2
    )
    
    # Run simulation
    env.run(until=args.simulate_time)


if __name__ == '__main__':
    main()
