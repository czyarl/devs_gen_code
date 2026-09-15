#!/usr/bin/env python3
"""
Reliable Data Transfer Simulation using Alternating Bit Protocol (ABP)
"""

import argparse
import sys
import json
import logging
import simpy


class EventLogger:
    """Handles logging of simulation events to stdout in JSONL format"""
    
    def __init__(self):
        pass
    
    def log(self, time, entity, event, payload):
        """Log an event"""
        event_record = {
            "time": round(time, 2),
            "entity": entity,
            "event": event,
            "payload": payload
        }
        print(json.dumps(event_record))
    
    def log_delay_start(self, time, entity, delay_type, duration):
        """Log delay start event"""
        self.log(time, entity, "delay_start", {
            "type": delay_type,
            "duration": duration
        })
    
    def log_packet_sent(self, time, seq_num, bit, is_retry):
        """Log packet sent event"""
        self.log(time, "sender", "packet_sent", {
            "seq_num": seq_num,
            "bit": bit,
            "is_retry": is_retry
        })
    
    def log_ack_received(self, time, ack_bit, is_valid):
        """Log ACK received event"""
        self.log(time, "sender", "ack_received", {
            "ack_bit": ack_bit,
            "is_valid": is_valid
        })
    
    def log_packet_received(self, time, seq_num, bit):
        """Log packet received event"""
        self.log(time, "receiver", "packet_received", {
            "seq_num": seq_num,
            "bit": bit
        })
    
    def log_packet_get(self, time, behavior, channel, noise_value):
        """Log packet fate determination event"""
        self.log(time, "subnet", "packet_get", {
            "behavior": behavior,
            "channel": channel,
            "noise_value": noise_value
        })


class Subnet:
    """Represents a communication channel with deterministic noise model"""
    
    def __init__(self, env, logger, name, channel_type, seed, channel_delay):
        self.env = env
        self.logger = logger
        self.name = name
        self.channel_type = channel_type  # "forward" or "backward"
        self.noise_level = seed
        self.channel_delay = channel_delay
        self.store = simpy.Store(env)
        self.dest = None
        env.process(self.run())
    
    def send(self, packet):
        """Send a packet through this subnet"""
        self.store.put(packet)
    
    def run(self):
        """Process packets through the subnet"""
        while True:
            packet = yield self.store.get()
            
            # Calculate noise level and determine packet fate
            self.noise_level = (17 * self.noise_level + 11) % 100
            noise_value = self.noise_level
            
            if noise_value < 10:
                # Packet is dropped
                self.logger.log_packet_get(
                    self.env.now,
                    "drop",
                    self.channel_type,
                    noise_value
                )
            else:
                # Packet is transmitted
                self.logger.log_packet_get(
                    self.env.now,
                    "pass",
                    self.channel_type,
                    noise_value
                )
                # Wait for channel delay
                yield self.env.timeout(self.channel_delay)
                # Deliver packet to destination
                if self.dest:
                    self.dest.receive(packet)


class Sender:
    """Sender entity using Alternating Bit Protocol"""
    
    def __init__(self, env, logger, total_packets, timeout, sender_delay, forward_subnet, backward_subnet):
        self.env = env
        self.logger = logger
        self.total_packets = total_packets
        self.timeout = timeout
        self.sender_delay = sender_delay
        self.forward_subnet = forward_subnet
        self.backward_subnet = backward_subnet
        
        self.seq_num = 1
        self.bit = 0
        self.packets_sent = 0
        self.current_packet = None
        self.timeout_event = None
        self.ack_received_event = None
        self.waiting_for_ack = False
        
        env.process(self.run())
    
    def run(self):
        """Main sender process"""
        while self.packets_sent < self.total_packets:
            # Prepare packet with delay
            self.logger.log_delay_start(
                self.env.now,
                "sender",
                "preparation",
                self.sender_delay
            )
            yield self.env.timeout(self.sender_delay)
            
            # Send packet
            is_retry = (self.current_packet is not None)
            
            packet = {
                'seq_num': self.seq_num,
                'bit': self.bit,
                'dest': None  # Will be set by subnet
            }
            self.current_packet = packet
            
            self.logger.log_packet_sent(
                self.env.now,
                self.seq_num,
                self.bit,
                is_retry
            )
            
            self.forward_subnet.send(packet)
            
            # Wait for ACK with timeout
            self.waiting_for_ack = True
            self.ack_received_event = self.env.event()
            self.timeout_event = self.env.event()
            
            # Start timeout process
            self.env.process(self.timeout_process())
            
            # Wait for either ACK or timeout
            yield simpy.AnyOf(self.env, [self.ack_received_event, self.timeout_event])
            
            self.waiting_for_ack = False
    
    def timeout_process(self):
        """Handle timeout and retransmission"""
        yield self.env.timeout(self.timeout)
        if self.waiting_for_ack:
            # Timeout occurred, retransmit
            self.timeout_event.succeed()
    
    def receive(self, packet):
        """Receive ACK packet"""
        ack_bit = packet['bit']
        is_valid = (ack_bit == self.bit)
        
        self.logger.log_ack_received(
            self.env.now,
            ack_bit,
            is_valid
        )
        
        if is_valid and self.waiting_for_ack:
            # Valid ACK received
            self.ack_received_event.succeed()
            self.packets_sent += 1
            self.seq_num += 1
            self.bit = 1 - self.bit  # Toggle bit
            self.current_packet = None


class Receiver:
    """Receiver entity"""
    
    def __init__(self, env, logger, receiver_delay, backward_subnet):
        self.env = env
        self.logger = logger
        self.receiver_delay = receiver_delay
        self.backward_subnet = backward_subnet
        
        self.buffer = None
        self.buffer_capacity = 1
        self.is_busy = False
        self.packet_available = env.event()
        
        env.process(self.run())
    
    def run(self):
        """Main receiver process"""
        while True:
            # Wait for packet to arrive in buffer
            while self.buffer is None:
                yield self.packet_available
                self.packet_available = self.env.event()
            
            # Process packet
            packet = self.buffer
            
            # Start processing delay
            self.logger.log_delay_start(
                self.env.now,
                "receiver",
                "processing",
                self.receiver_delay
            )
            
            yield self.env.timeout(self.receiver_delay)
            
            # Packet successfully received
            self.logger.log_packet_received(
                self.env.now,
                packet['seq_num'],
                packet['bit']
            )
            
            # Send ACK
            ack_packet = {
                'bit': packet['bit'],
                'dest': None  # Will be set by subnet
            }
            self.backward_subnet.send(ack_packet)
            
            # Clear buffer
            self.buffer = None
    
    def receive(self, packet):
        """Receive packet from forward subnet"""
        if self.buffer is None:
            self.buffer = packet
            self.packet_available.succeed()
        # If buffer is full, packet is dropped (only first one is stored)


def setup_simulation(args):
    """Set up the simulation environment and all entities"""
    env = simpy.Environment()
    logger = EventLogger()
    
    # Create subnets
    forward_subnet = Subnet(
        env, logger, "forward_subnet", "forward",
        args.seed, args.channel_delay
    )
    backward_subnet = Subnet(
        env, logger, "backward_subnet", "backward",
        args.seed, args.channel_delay
    )
    
    # Create sender and receiver
    sender = Sender(
        env, logger, args.total_packets, args.timeout,
        args.sender_delay, forward_subnet, backward_subnet
    )
    receiver = Receiver(
        env, logger, args.receiver_delay, backward_subnet
    )
    
    # Set destinations for subnets
    forward_subnet.dest = receiver
    backward_subnet.dest = sender
    
    return env


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Reliable Data Transfer Simulation using ABP'
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
        help='Initialization seed for noise generator'
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=20,
        help='Sender timeout duration in ms'
    )
    parser.add_argument(
        '--sender_delay',
        type=int,
        default=10,
        help='Sender preparation delay in ms'
    )
    parser.add_argument(
        '--receiver_delay',
        type=int,
        default=10,
        help='Receiver processing delay in ms'
    )
    parser.add_argument(
        '--channel_delay',
        type=int,
        default=3,
        help='Subnet transmission delay in ms'
    )
    parser.add_argument(
        '--simulate_time',
        type=int,
        default=1000,
        help='Total simulation time in ms'
    )
    
    args = parser.parse_args()
    
    # Set up and run simulation
    env = setup_simulation(args)
    env.run(until=args.simulate_time)


if __name__ == '__main__':
    main()