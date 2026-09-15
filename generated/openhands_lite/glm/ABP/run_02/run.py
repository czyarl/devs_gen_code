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
        pass
    
    def log(self, time, entity, event, payload):
        """Log an event to stdout in JSONL format"""
        record = {
            "time": round(time, 2),
            "entity": entity,
            "event": event,
            "payload": payload
        }
        print(json.dumps(record))
    
    def log_sender_delay_start(self, time, duration):
        self.log(time, "sender", "delay_start", {"type": "preparation", "duration": duration})
    
    def log_sender_packet_sent(self, time, seq_num, bit, is_retry):
        self.log(time, "sender", "packet_sent", {"seq_num": seq_num, "bit": bit, "is_retry": is_retry})
    
    def log_sender_ack_received(self, time, ack_bit, is_valid):
        self.log(time, "sender", "ack_received", {"ack_bit": ack_bit, "is_valid": is_valid})
    
    def log_receiver_delay_start(self, time, duration):
        self.log(time, "receiver", "delay_start", {"type": "processing", "duration": duration})
    
    def log_receiver_packet_received(self, time, seq_num, bit):
        self.log(time, "receiver", "packet_received", {"seq_num": seq_num, "bit": bit})
    
    def log_subnet_packet_get(self, time, behavior, channel, noise_value):
        self.log(time, "subnet", "packet_get", {"behavior": behavior, "channel": channel, "noise_value": noise_value})


class Subnet:
    """Represents a transmission channel with deterministic noise"""
    
    def __init__(self, env, logger, name, channel_type, seed, channel_delay):
        self.env = env
        self.logger = logger
        self.name = name
        self.channel_type = channel_type  # "forward" or "backward"
        self.noise_level = seed
        self.channel_delay = channel_delay
        self.input_queue = simpy.Store(env)
        self.output_queue = simpy.Store(env)
        env.process(self.run())
    
    def run(self):
        """Process packets through the subnet"""
        while True:
            packet = yield self.input_queue.get()
            
            # Calculate noise level and determine packet fate
            self.noise_level = (17 * self.noise_level + 11) % 100
            noise_value = self.noise_level
            
            # Log packet fate determination
            if noise_value < 10:
                behavior = "drop"
                self.logger.log_subnet_packet_get(self.env.now, behavior, self.channel_type, noise_value)
                # Packet is dropped, don't forward it
            else:
                behavior = "pass"
                self.logger.log_subnet_packet_get(self.env.now, behavior, self.channel_type, noise_value)
                # Wait for channel delay then forward
                yield self.env.timeout(self.channel_delay)
                yield self.output_queue.put(packet)


class Sender:
    """Implements the Sender side of ABP"""
    
    def __init__(self, env, logger, total_packets, timeout, sender_delay, subnet1, subnet2):
        self.env = env
        self.logger = logger
        self.total_packets = total_packets
        self.timeout = timeout
        self.sender_delay = sender_delay
        self.subnet1 = subnet1  # Forward channel
        self.subnet2 = subnet2  # Backward channel (for ACKs)
        
        self.current_seq = 1
        self.current_bit = 0
        self.packets_sent = 0
        self.timer_process = None
        self.waiting_for_ack = False
        self.current_packet = None
        
        env.process(self.run())
    
    def run(self):
        """Main sender process"""
        while self.packets_sent < self.total_packets:
            # Prepare packet
            self.current_packet = {
                "seq_num": self.current_seq,
                "bit": self.current_bit
            }
            
            # Preparation delay
            self.logger.log_sender_delay_start(self.env.now, self.sender_delay)
            yield self.env.timeout(self.sender_delay)
            
            # Send packet
            is_retry = False
            self.logger.log_sender_packet_sent(self.env.now, self.current_seq, self.current_bit, is_retry)
            yield self.subnet1.input_queue.put(self.current_packet)
            
            # Start timer and wait for ACK
            self.waiting_for_ack = True
            ack_received = False
            valid_ack = False
            
            while not valid_ack and self.packets_sent < self.total_packets:
                # Start timeout timer
                timeout_event = self.env.timeout(self.timeout)
                
                # Wait for either timeout or ACK
                ack_event = self.subnet2.output_queue.get()
                
                result = yield self.env.process(self._wait_for_ack_or_timeout(timeout_event, ack_event))
                
                if result == "timeout":
                    # Retransmit
                    is_retry = True
                    self.logger.log_sender_packet_sent(self.env.now, self.current_seq, self.current_bit, is_retry)
                    yield self.subnet1.input_queue.put(self.current_packet)
                else:
                    # ACK received
                    ack = result
                    is_valid = (ack["bit"] == self.current_bit)
                    self.logger.log_sender_ack_received(self.env.now, ack["bit"], is_valid)
                    
                    if is_valid:
                        valid_ack = True
                        self.packets_sent += 1
                        self.current_seq += 1
                        self.current_bit = 1 - self.current_bit  # Toggle bit
            
            self.waiting_for_ack = False
    
    def _wait_for_ack_or_timeout(self, timeout_event, ack_event):
        """Helper to wait for either timeout or ACK"""
        result = yield timeout_event | ack_event
        
        if timeout_event in result:
            return "timeout"
        else:
            return ack_event.value


class Receiver:
    """Implements the Receiver side of ABP"""
    
    def __init__(self, env, logger, receiver_delay, subnet1, subnet2):
        self.env = env
        self.logger = logger
        self.receiver_delay = receiver_delay
        self.subnet1 = subnet1  # Forward channel (from sender)
        self.subnet2 = subnet2  # Backward channel (for ACKs)
        
        self.buffer = None
        self.buffer_capacity = 1
        self.is_busy = False
        
        env.process(self.run())
    
    def run(self):
        """Main receiver process"""
        while True:
            # Wait for packet
            packet = yield self.subnet1.output_queue.get()
            
            # Check if buffer is available
            if self.buffer is None:
                # Store in buffer
                self.buffer = packet
                
                # Processing delay
                self.logger.log_receiver_delay_start(self.env.now, self.receiver_delay)
                yield self.env.timeout(self.receiver_delay)
                
                # Process packet
                self.logger.log_receiver_packet_received(self.env.now, packet["seq_num"], packet["bit"])
                
                # Send ACK
                ack = {"bit": packet["bit"]}
                yield self.subnet2.input_queue.put(ack)
                
                # Clear buffer
                self.buffer = None
            else:
                # Buffer is full, drop the packet (only first one is stored)
                pass


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Alternating Bit Protocol Simulation")
    parser.add_argument("--total_packets", type=int, required=True,
                        help="Total number of packets to send")
    parser.add_argument("--seed", type=int, default=42,
                        help="Initialization seed for noise generator")
    parser.add_argument("--timeout", type=int, default=20,
                        help="Sender timeout duration in ms")
    parser.add_argument("--sender_delay", type=int, default=10,
                        help="Sender preparation delay in ms")
    parser.add_argument("--receiver_delay", type=int, default=10,
                        help="Receiver processing delay in ms")
    parser.add_argument("--channel_delay", type=int, default=3,
                        help="Subnet transmission delay in ms")
    parser.add_argument("--simulate_time", type=int, default=1000,
                        help="Total simulation time in ms")
    
    args = parser.parse_args()
    
    # Setup logging to stderr
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        stream=sys.stderr
    )
    
    # Create simulation environment
    env = simpy.Environment()
    logger = Logger()
    
    # Create subnets (channels)
    subnet1 = Subnet(env, logger, "subnet1", "forward", args.seed, args.channel_delay)
    subnet2 = Subnet(env, logger, "subnet2", "backward", args.seed, args.channel_delay)
    
    # Create sender and receiver
    sender = Sender(env, logger, args.total_packets, args.timeout, args.sender_delay, subnet1, subnet2)
    receiver = Receiver(env, logger, args.receiver_delay, subnet1, subnet2)
    
    # Run simulation
    env.run(until=args.simulate_time)


if __name__ == "__main__":
    main()
