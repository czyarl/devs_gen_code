#!/usr/bin/env python3
"""
Alternating Bit Protocol (ABP) Simulation
Implements reliable data transfer with deterministic noise interference.
"""

import argparse
import sys
import json
import logging
from collections import deque
import simpy


class Logger:
    """Custom logger for JSONL output to stdout."""
    
    def __init__(self):
        # Create a separate logger for debug output to stderr
        self.debug_logger = logging.getLogger('abp_debug')
        self.debug_logger.setLevel(logging.DEBUG)
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.DEBUG)
        debug_formatter = logging.Formatter('[%(levelname)s] %(message)s')
        stderr_handler.setFormatter(debug_formatter)
        self.debug_logger.addHandler(stderr_handler)
    
    def log_event(self, time, entity, event, payload):
        """Log an event in JSONL format to stdout."""
        record = {
            "time": round(time, 2),
            "entity": entity,
            "event": event,
            "payload": payload
        }
        # Direct print to stdout to avoid logging prefixes
        print(json.dumps(record))
    
    def debug(self, message):
        """Log debug message to stderr."""
        self.debug_logger.debug(message)


class Subnet:
    """Represents a transmission channel with deterministic noise."""
    
    def __init__(self, env, name, direction, channel_delay, seed, logger):
        self.env = env
        self.name = name
        self.direction = direction  # "forward" or "backward"
        self.channel_delay = channel_delay
        self.noise_level = seed
        self.logger = logger
        self.input_queue = simpy.Store(env)
        self.output_queue = simpy.Store(env)
        self.env.process(self.run())
    
    def run(self):
        """Process packets through the subnet."""
        while True:
            packet = yield self.input_queue.get()
            
            # Calculate noise level and determine packet fate
            new_noise = (17 * self.noise_level + 11) % 100
            behavior = "drop" if new_noise < 10 else "pass"
            
            # Log packet fate determination
            self.logger.log_event(
                self.env.now,
                "subnet",
                "packet_get",
                {
                    "behavior": behavior,
                    "channel": self.direction,
                    "noise_value": new_noise
                }
            )
            
            # Update noise level for next packet
            self.noise_level = new_noise
            
            # If packet passes, transmit after channel delay
            if behavior == "pass":
                yield self.env.timeout(self.channel_delay)
                yield self.output_queue.put(packet)
            # If dropped, packet vanishes (nothing to do)
    
    def send(self, packet):
        """Send a packet through the subnet."""
        return self.input_queue.put(packet)
    
    def receive(self):
        """Receive a packet from the subnet."""
        return self.output_queue.get()


class Receiver:
    """Receives packets and sends ACKs."""
    
    def __init__(self, env, receiver_delay, subnet_backward, logger):
        self.env = env
        self.receiver_delay = receiver_delay
        self.subnet_backward = subnet_backward
        self.logger = logger
        self.input_queue = simpy.Store(env)
        self.buffer = None
        self.busy = False
        self.env.process(self.run())
    
    def run(self):
        """Process incoming packets."""
        while True:
            packet = yield self.input_queue.get()
            
            # If buffer is full (busy), drop the packet
            if self.buffer is not None:
                self.logger.debug(f"Receiver buffer full, dropping packet: {packet}")
                continue
            
            # Store packet in buffer
            self.buffer = packet
            self.busy = True
            
            # Log processing delay start
            self.logger.log_event(
                self.env.now,
                "receiver",
                "delay_start",
                {
                    "type": "processing",
                    "duration": self.receiver_delay
                }
            )
            
            # Wait for processing delay
            yield self.env.timeout(self.receiver_delay)
            
            # Get packet from buffer
            packet = self.buffer
            self.buffer = None
            self.busy = False
            
            # Log packet received
            self.logger.log_event(
                self.env.now,
                "receiver",
                "packet_received",
                {
                    "seq_num": packet["seq_num"],
                    "bit": packet["bit"]
                }
            )
            
            # Send ACK with the same bit
            ack = {
                "type": "ack",
                "bit": packet["bit"]
            }
            yield self.subnet_backward.send(ack)
    
    def receive_packet(self, packet):
        """Receive a packet from the forward subnet."""
        return self.input_queue.put(packet)


class Sender:
    """Sends packets and waits for ACKs."""
    
    def __init__(self, env, total_packets, timeout, sender_delay, 
                 subnet_forward, subnet_backward, logger):
        self.env = env
        self.total_packets = total_packets
        self.timeout = timeout
        self.sender_delay = sender_delay
        self.subnet_forward = subnet_forward
        self.subnet_backward = subnet_backward
        self.logger = logger
        self.packets_sent = 0
        self.current_seq = 1
        self.current_bit = 0
        self.env.process(self.run())
    
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
                    "duration": self.sender_delay
                }
            )
            
            # Wait for preparation delay
            yield self.env.timeout(self.sender_delay)
            
            # Create packet
            packet = {
                "seq_num": self.current_seq,
                "bit": self.current_bit
            }
            
            # Send packet
            is_retry = False
            self.logger.log_event(
                self.env.now,
                "sender",
                "packet_sent",
                {
                    "seq_num": packet["seq_num"],
                    "bit": packet["bit"],
                    "is_retry": is_retry
                }
            )
            yield self.subnet_forward.send(packet)
            
            # Wait for ACK with timeout
            ack_received = False
            while not ack_received:
                # Start timeout timer
                timeout_event = self.env.timeout(self.timeout)
                
                # Wait for either ACK or timeout
                ack_event = self.subnet_backward.receive()
                result = yield timeout_event | ack_event
                
                if timeout_event in result:
                    # Timeout expired, retransmit
                    self.logger.log_event(
                        self.env.now,
                        "sender",
                        "packet_sent",
                        {
                            "seq_num": packet["seq_num"],
                            "bit": packet["bit"],
                            "is_retry": True
                        }
                    )
                    yield self.subnet_forward.send(packet)
                else:
                    # ACK received
                    ack = ack_event.value
                    
                    # Check if ACK is valid
                    is_valid = (ack["bit"] == self.current_bit)
                    
                    self.logger.log_event(
                        self.env.now,
                        "sender",
                        "ack_received",
                        {
                            "ack_bit": ack["bit"],
                            "is_valid": is_valid
                        }
                    )
                    
                    if is_valid:
                        # Valid ACK, move to next packet
                        ack_received = True
                        self.packets_sent += 1
                        self.current_seq += 1
                        self.current_bit = 1 - self.current_bit  # Toggle bit


def main():
    """Main entry point for the simulation."""
    parser = argparse.ArgumentParser(
        description="Alternating Bit Protocol (ABP) Simulation"
    )
    parser.add_argument(
        "--total_packets",
        type=int,
        required=True,
        help="Total number of packets to send"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Initialization seed for noise generator"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="Sender timeout duration in ms"
    )
    parser.add_argument(
        "--sender_delay",
        type=int,
        default=10,
        help="Sender preparation delay in ms"
    )
    parser.add_argument(
        "--receiver_delay",
        type=int,
        default=10,
        help="Receiver processing delay in ms"
    )
    parser.add_argument(
        "--channel_delay",
        type=int,
        default=3,
        help="Subnet transmission delay in ms"
    )
    parser.add_argument(
        "--simulate_time",
        type=int,
        default=1000,
        help="Total simulation time in ms"
    )
    
    args = parser.parse_args()
    
    # Create logger
    logger = Logger()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create subnets (channels)
    subnet_forward = Subnet(
        env, "subnet1", "forward", args.channel_delay, args.seed, logger
    )
    subnet_backward = Subnet(
        env, "subnet2", "backward", args.channel_delay, args.seed, logger
    )
    
    # Create receiver
    receiver = Receiver(
        env, args.receiver_delay, subnet_backward, logger
    )
    
    # Create sender
    sender = Sender(
        env, args.total_packets, args.timeout, args.sender_delay,
        subnet_forward, subnet_backward, logger
    )
    
    # Connect forward subnet to receiver
    env.process(forward_to_receiver(env, subnet_forward, receiver))
    
    # Run simulation
    env.run(until=args.simulate_time)


def forward_to_receiver(env, subnet, receiver):
    """Forward packets from subnet to receiver."""
    while True:
        packet = yield subnet.receive()
        yield receiver.receive_packet(packet)


if __name__ == "__main__":
    main()