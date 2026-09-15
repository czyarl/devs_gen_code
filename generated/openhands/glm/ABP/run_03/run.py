#!/usr/bin/env python3
"""
Alternating Bit Protocol (ABP) Simulation with Deterministic Noise
"""

import argparse
import sys
import json
from typing import Dict, Any


class EventLogger:
    """Logger for simulation events in JSONL format"""
    
    def __init__(self):
        pass
    
    def log_event(self, time: float, entity: str, event: str, payload: Dict[str, Any]):
        """Log an event to stdout in JSONL format"""
        event_record = {
            "time": round(time, 2),
            "entity": entity,
            "event": event,
            "payload": payload
        }
        print(json.dumps(event_record), file=sys.stdout, flush=True)


class Subnet:
    """Simulates a transmission channel with deterministic noise"""
    
    def __init__(self, env, name: str, direction: str, channel_delay: float, 
                 seed: int, logger: EventLogger):
        self.env = env
        self.name = name
        self.direction = direction  # "forward" or "backward"
        self.channel_delay = channel_delay
        self.noise_level = seed
        self.logger = logger
        self.input_pipe = env.process(self._receive_packets())
    
    def _receive_packets(self):
        """Process incoming packets"""
        while True:
            packet = yield self.input_pipe.get()
            
            # Calculate noise level
            new_noise = (17 * self.noise_level + 11) % 100
            
            # Determine packet fate
            behavior = "drop" if new_noise < 10 else "pass"
            
            # Log packet fate determination
            self.logger.log_event(
                time=self.env.now,
                entity="subnet",
                event="packet_get",
                payload={
                    "behavior": behavior,
                    "channel": self.direction,
                    "noise_value": new_noise
                }
            )
            
            # Update noise level for next packet
            self.noise_level = new_noise
            
            # If packet passes, transmit after delay
            if behavior == "pass":
                yield self.env.timeout(self.channel_delay)
                if hasattr(self, 'output_pipe'):
                    self.output_pipe.put(packet)
    
    def send(self, packet: Dict[str, Any]):
        """Send a packet through this subnet"""
        self.input_pipe.put(packet)


class Sender:
    """Implements the Sender side of ABP"""
    
    def __init__(self, env, total_packets: int, timeout: float, 
                 sender_delay: float, logger: EventLogger):
        self.env = env
        self.total_packets = total_packets
        self.timeout = timeout
        self.sender_delay = sender_delay
        self.logger = logger
        
        self.seq_num = 1
        self.current_bit = 0
        self.packets_sent = 0
        self.waiting_for_ack = False
        
        # Communication channels
        self.to_subnet = None
        self.from_subnet = None
    
    def set_channels(self, to_subnet, from_subnet):
        """Set communication channels"""
        self.to_subnet = to_subnet
        self.from_subnet = from_subnet
    
    def run(self):
        """Main sender process"""
        while self.packets_sent < self.total_packets:
            # Preparation delay
            self.logger.log_event(
                time=self.env.now,
                entity="sender",
                event="delay_start",
                payload={"type": "preparation", "duration": self.sender_delay}
            )
            yield self.env.timeout(self.sender_delay)
            
            # Send packet
            is_retry = self.waiting_for_ack
            packet = {
                "seq_num": self.seq_num,
                "bit": self.current_bit
            }
            
            self.logger.log_event(
                time=self.env.now,
                entity="sender",
                event="packet_sent",
                payload={
                    "seq_num": self.seq_num,
                    "bit": self.current_bit,
                    "is_retry": is_retry
                }
            )
            
            self.to_subnet.send(packet)
            
            # Start timer and wait for ACK
            self.waiting_for_ack = True
            
            # Wait for either ACK or timeout
            ack_received = False
            while not ack_received:
                # Create timeout event
                timeout_event = self.env.timeout(self.timeout)
                
                # Wait for either ACK or timeout
                get_ack = self.from_subnet.get()
                result = yield self.env.any_of([get_ack, timeout_event])
                
                if get_ack in result:
                    # ACK received
                    ack = result[get_ack]
                    
                    # Validate ACK
                    ack_bit = ack.get("bit")
                    is_valid = (ack_bit == self.current_bit)
                    
                    self.logger.log_event(
                        time=self.env.now,
                        entity="sender",
                        event="ack_received",
                        payload={"ack_bit": ack_bit, "is_valid": is_valid}
                    )
                    
                    if is_valid:
                        ack_received = True
                        self.waiting_for_ack = False
                        self.packets_sent += 1
                        self.seq_num += 1
                        self.current_bit = 1 - self.current_bit  # Toggle bit
                else:
                    # Timeout occurred, retransmit
                    break


class Receiver:
    """Implements the Receiver side of ABP"""
    
    def __init__(self, env, receiver_delay: float, logger: EventLogger):
        self.env = env
        self.receiver_delay = receiver_delay
        self.logger = logger
        
        self.buffer = None
        self.buffer_capacity = 1
        self.is_busy = False
        
        # Communication channels
        self.to_subnet = None
        self.from_subnet = None
    
    def set_channels(self, to_subnet, from_subnet):
        """Set communication channels"""
        self.to_subnet = to_subnet
        self.from_subnet = from_subnet
    
    def run(self):
        """Main receiver process"""
        while True:
            # Wait for packet
            packet = yield self.from_subnet.get()
            
            # Check if receiver is busy
            if self.is_busy:
                # Buffer the packet (only one can be stored)
                if self.buffer is None:
                    self.buffer = packet
                continue
            
            # Start processing
            self.is_busy = True
            self.logger.log_event(
                time=self.env.now,
                entity="receiver",
                event="delay_start",
                payload={"type": "processing", "duration": self.receiver_delay}
            )
            
            # Processing delay
            yield self.env.timeout(self.receiver_delay)
            
            # Process packet
            seq_num = packet["seq_num"]
            bit = packet["bit"]
            
            self.logger.log_event(
                time=self.env.now,
                entity="receiver",
                event="packet_received",
                payload={"seq_num": seq_num, "bit": bit}
            )
            
            # Send ACK
            ack = {"bit": bit}
            self.to_subnet.send(ack)
            
            # Mark as not busy
            self.is_busy = False
            
            # Process buffered packet if any
            if self.buffer is not None:
                buffered_packet = self.buffer
                self.buffer = None
                self.from_subnet.put(buffered_packet)


def main():
    """Main simulation function"""
    parser = argparse.ArgumentParser(
        description='Alternating Bit Protocol Simulation with Deterministic Noise'
    )
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
    
    # Create simulation environment
    import simpy
    env = simpy.Environment()
    
    # Create event logger
    logger = EventLogger()
    
    # Create communication pipes
    sender_to_subnet = simpy.Store(env)
    subnet_to_receiver = simpy.Store(env)
    receiver_to_subnet = simpy.Store(env)
    subnet_to_sender = simpy.Store(env)
    
    # Create subnets
    subnet1 = Subnet(env, "subnet1", "forward", args.channel_delay, 
                     args.seed, logger)
    subnet1.input_pipe = sender_to_subnet
    subnet1.output_pipe = subnet_to_receiver
    
    subnet2 = Subnet(env, "subnet2", "backward", args.channel_delay, 
                     args.seed, logger)
    subnet2.input_pipe = receiver_to_subnet
    subnet2.output_pipe = subnet_to_sender
    
    # Create sender and receiver
    sender = Sender(env, args.total_packets, args.timeout, 
                    args.sender_delay, logger)
    sender.set_channels(subnet1, subnet_to_sender)
    
    receiver = Receiver(env, args.receiver_delay, logger)
    receiver.set_channels(subnet2, subnet_to_receiver)
    
    # Start processes
    env.process(sender.run())
    env.process(receiver.run())
    
    # Run simulation
    env.run(until=args.simulate_time)


if __name__ == '__main__':
    main()