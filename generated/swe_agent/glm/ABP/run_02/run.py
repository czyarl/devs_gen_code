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


class Logger:
    """Custom logger for JSONL output to stdout"""
    
    def __init__(self):
        # Create stdout handler for JSONL output
        self.stdout_handler = logging.StreamHandler(sys.stdout)
        self.stdout_handler.setLevel(logging.INFO)
        self.stdout_handler.setFormatter(logging.Formatter('%(message)s'))
        
        # Create stderr handler for debug info
        self.stderr_handler = logging.StreamHandler(sys.stderr)
        self.stderr_handler.setLevel(logging.DEBUG)
        self.stderr_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    
    def log_event(self, time, entity, event, payload):
        """Log an event in JSONL format to stdout"""
        record = {
            "time": float(time),
            "entity": entity,
            "event": event,
            "payload": payload
        }
        # Directly print to stdout to avoid logging overhead
        print(json.dumps(record))
    
    def debug(self, message):
        """Log debug message to stderr"""
        print(f"DEBUG: {message}", file=sys.stderr)


class Subnet:
    """Represents a transmission channel with deterministic noise interference"""
    
    def __init__(self, env, name, direction, seed, channel_delay, logger):
        self.env = env
        self.name = name
        self.direction = direction  # "forward" or "backward"
        self.noise_level = seed
        self.channel_delay = channel_delay
        self.logger = logger
        self.store = simpy.Store(env)
        self.receiver = None  # Will be set for forward channel
        self.sender = None    # Will be set for backward channel
        self.env.process(self.run())
    
    def run(self):
        """Process packets through the subnet"""
        while True:
            packet = yield self.store.get()
            
            # Calculate new noise level: x_new = (17 * x_old + 11) mod 100
            new_noise = (17 * self.noise_level + 11) % 100
            
            # Determine packet fate
            if new_noise < 10:
                # Packet is dropped
                self.logger.log_event(
                    self.env.now,
                    "subnet",
                    "packet_get",
                    {
                        "behavior": "drop",
                        "channel": self.direction,
                        "noise_value": new_noise
                    }
                )
            else:
                # Packet is transmitted
                self.logger.log_event(
                    self.env.now,
                    "subnet",
                    "packet_get",
                    {
                        "behavior": "pass",
                        "channel": self.direction,
                        "noise_value": new_noise
                    }
                )
                
                # Wait for channel delay
                yield self.env.timeout(self.channel_delay)
                
                # Send packet to destination
                if self.direction == "forward":
                    if self.receiver:
                        self.receiver.receive_packet(packet)
                else:
                    if self.sender:
                        self.sender.receive_ack(packet)
            
            # Update noise level for next packet
            self.noise_level = new_noise
    
    def send(self, packet):
        """Send a packet through this subnet"""
        self.store.put(packet)


class Sender:
    """Implements the Sender side of ABP"""
    
    def __init__(self, env, total_packets, timeout, sender_delay, subnet1, logger):
        self.env = env
        self.total_packets = total_packets
        self.timeout = timeout
        self.sender_delay = sender_delay
        self.subnet1 = subnet1
        self.logger = logger
        
        self.seq_num = 1
        self.current_bit = 0
        self.packets_sent = 0
        self.timer_process = None
        self.waiting_for_ack = False
        self.ack_store = simpy.Store(env)
    
    def start(self):
        """Start the sender process"""
        self.env.process(self.run())
    
    def run(self):
        """Main sender process"""
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
            
            # Send packet
            is_retry = self.packets_sent > 0 and self.waiting_for_ack
            packet = {
                'seq_num': self.seq_num,
                'bit': self.current_bit,
                'sender': self,
                'receiver': None  # Will be set by subnet
            }
            
            self.logger.log_event(
                self.env.now,
                "sender",
                "packet_sent",
                {
                    "seq_num": self.seq_num,
                    "bit": self.current_bit,
                    "is_retry": is_retry
                }
            )
            
            # Send through subnet
            self.subnet1.send(packet)
            
            # Start timer
            self.waiting_for_ack = True
            self.timer_process = self.env.process(self.timer())
            
            # Wait for ACK
            ack = yield self.ack_store.get()
            
            # Cancel timer if still running
            if self.timer_process.is_alive:
                self.timer_process.interrupt()
            
            # Process ACK
            self.logger.log_event(
                self.env.now,
                "sender",
                "ack_received",
                {
                    "ack_bit": ack['bit'],
                    "is_valid": ack['bit'] == self.current_bit
                }
            )
            
            if ack['bit'] == self.current_bit:
                # Valid ACK, move to next packet
                self.packets_sent += 1
                self.seq_num += 1
                self.current_bit = 1 - self.current_bit  # Toggle bit
                self.waiting_for_ack = False
    
    def timer(self):
        """Timer process for retransmission"""
        try:
            yield self.env.timeout(self.timeout)
            # Timer expired, retransmit
            self.ack_store.put({'bit': 1 - self.current_bit})  # Invalid ACK to trigger retransmit
        except simpy.Interrupt:
            # Timer was cancelled (ACK received)
            pass
    
    def receive_ack(self, ack_packet):
        """Receive ACK from subnet"""
        self.ack_store.put(ack_packet)


class Receiver:
    """Implements the Receiver side of ABP"""
    
    def __init__(self, env, receiver_delay, subnet2, logger):
        self.env = env
        self.receiver_delay = receiver_delay
        self.subnet2 = subnet2
        self.logger = logger
        
        self.buffer = None
        self.buffer_capacity = 1
        self.is_busy = False
        self.packet_queue = deque()
    
    def receive_packet(self, packet):
        """Receive a packet from subnet"""
        if not self.is_busy:
            # Not busy, process immediately
            self.is_busy = True
            self.buffer = packet
            self.env.process(self.process_packet())
        else:
            # Busy, buffer the packet (only keep the first one)
            if len(self.packet_queue) == 0:
                self.packet_queue.append(packet)
    
    def process_packet(self):
        """Process a received packet"""
        packet = self.buffer
        
        # Start processing delay
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
            'bit': packet['bit'],
            'sender': None,  # Will be set by subnet
            'receiver': None
        }
        self.subnet2.send(ack_packet)
        
        # Check if there are more packets to process
        if len(self.packet_queue) > 0:
            self.buffer = self.packet_queue.popleft()
            self.env.process(self.process_packet())
        else:
            self.is_busy = False
            self.buffer = None


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Alternating Bit Protocol (ABP) Simulation with Deterministic Noise Interference'
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
    
    # Create logger
    logger = Logger()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create subnets
    subnet1 = Subnet(env, "subnet1", "forward", args.seed, args.channel_delay, logger)
    subnet2 = Subnet(env, "subnet2", "backward", args.seed, args.channel_delay, logger)
    
    # Create receiver
    receiver = Receiver(env, args.receiver_delay, subnet2, logger)
    
    # Create sender
    sender = Sender(env, args.total_packets, args.timeout, args.sender_delay, subnet1, logger)
    
    # Link receiver to subnet1
    subnet1.receiver = receiver
    
    # Link sender to subnet2
    subnet2.sender = sender
    
    # Start sender process (after all links are established)
    sender.start()
    
    # Run simulation
    env.run(until=args.simulate_time)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())