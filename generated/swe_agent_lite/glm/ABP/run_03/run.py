#!/usr/bin/env python3
"""
Alternating Bit Protocol (ABP) Simulation with Deterministic Noise Interference
"""

import argparse
import sys
import json
import logging
import simpy


class EventLogger:
    """Handles logging events to stdout in JSONL format"""
    
    def __init__(self):
        self.logger = logging.getLogger('event_logger')
        self.logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
    
    def log_event(self, time, entity, event, payload):
        """Log an event in JSONL format"""
        event_record = {
            "time": round(time, 2),
            "entity": entity,
            "event": event,
            "payload": payload
        }
        self.logger.info(json.dumps(event_record))


class Subnet:
    """Represents a transmission channel with deterministic noise interference"""
    
    def __init__(self, env, name, direction, seed, channel_delay, event_logger, destination):
        self.env = env
        self.name = name
        self.direction = direction  # "forward" or "backward"
        self.noise_level = seed
        self.channel_delay = channel_delay
        self.event_logger = event_logger
        self.destination = destination
        self.store = simpy.Store(env)
        self.env.process(self.run())
    
    def run(self):
        """Process packets through the subnet"""
        while True:
            packet = yield self.store.get()
            
            # Calculate noise level and determine packet fate
            new_noise = (17 * self.noise_level + 11) % 100
            behavior = "drop" if new_noise < 10 else "pass"
            
            # Log packet fate determination
            self.event_logger.log_event(
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
            
            # If packet passes, transmit after channel delay
            if behavior == "pass":
                yield self.env.timeout(self.channel_delay)
                # Send to destination
                if self.direction == "forward":
                    self.destination.put(packet)
                else:  # backward
                    self.destination.receive_ack(packet)
    
    def put(self, packet):
        """Receive a packet for transmission"""
        self.store.put(packet)


class Sender:
    """Implements the Sender in ABP with stop-and-wait protocol"""
    
    def __init__(self, env, total_packets, timeout, sender_delay, 
                 forward_subnet, event_logger):
        self.env = env
        self.total_packets = total_packets
        self.timeout = timeout
        self.sender_delay = sender_delay
        self.forward_subnet = forward_subnet
        self.event_logger = event_logger
        
        self.seq_num = 1
        self.current_bit = 0
        self.packets_sent = 0
        self.ack_store = simpy.Store(env)
        
        self.env.process(self.run())
    
    def run(self):
        """Main sender process"""
        while self.packets_sent < self.total_packets:
            # Preparation delay
            self.event_logger.log_event(
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
            is_retry = (self.packets_sent > 0 and 
                       self.seq_num == self.packets_sent + 1)
            
            packet = {
                'seq_num': self.seq_num,
                'bit': self.current_bit,
                'destination': self.forward_subnet
            }
            
            self.event_logger.log_event(
                time=self.env.now,
                entity="sender",
                event="packet_sent",
                payload={
                    "seq_num": self.seq_num,
                    "bit": self.current_bit,
                    "is_retry": is_retry
                }
            )
            
            self.forward_subnet.put(packet)
            
            # Wait for ACK with timeout
            timeout_event = self.env.timeout(self.timeout)
            ack_event = self.ack_store.get()
            
            # Wait for either timeout or ACK
            result = yield timeout_event | ack_event
            
            if timeout_event in result:
                # Timeout occurred, retry (loop continues)
                pass
            else:
                # ACK received
                ack = result[ack_event]
                ack_bit = ack['bit']
                is_valid = (ack_bit == self.current_bit)
                
                self.event_logger.log_event(
                    time=self.env.now,
                    entity="sender",
                    event="ack_received",
                    payload={
                        "ack_bit": ack_bit,
                        "is_valid": is_valid
                    }
                )
                
                if is_valid:
                    # Move to next packet
                    self.packets_sent += 1
                    self.seq_num += 1
                    self.current_bit = 1 - self.current_bit
                # If invalid, retry (loop continues)
    
    def receive_ack(self, ack):
        """Receive an ACK packet"""
        self.ack_store.put(ack)


class Receiver:
    """Implements the Receiver in ABP with buffer capacity 1"""
    
    def __init__(self, env, receiver_delay, backward_subnet, event_logger):
        self.env = env
        self.receiver_delay = receiver_delay
        self.backward_subnet = backward_subnet
        self.event_logger = event_logger
        
        self.packet_store = simpy.Store(env, capacity=1)
        self.processing = False
        
        self.env.process(self.run())
    
    def run(self):
        """Main receiver process"""
        while True:
            # Wait for packet
            packet = yield self.packet_store.get()
            
            # Start processing delay
            self.event_logger.log_event(
                time=self.env.now,
                entity="receiver",
                event="delay_start",
                payload={
                    "type": "processing",
                    "duration": float(self.receiver_delay)
                }
            )
            
            yield self.env.timeout(self.receiver_delay)
            
            # Packet successfully received
            self.event_logger.log_event(
                time=self.env.now,
                entity="receiver",
                event="packet_received",
                payload={
                    "seq_num": packet['seq_num'],
                    "bit": packet['bit']
                }
            )
            
            # Send ACK
            ack = {
                'bit': packet['bit'],
                'destination': self.backward_subnet
            }
            self.backward_subnet.put(ack)
    
    def put(self, packet):
        """Receive a packet (buffered if processing)"""
        try:
            self.packet_store.put_nowait(packet)
        except simpy.resources.store.StoreFull:
            # Buffer full, packet dropped
            pass


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
    
    # Setup logging for stderr (debug/info messages)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        stream=sys.stderr
    )
    
    # Create event logger for stdout
    event_logger = EventLogger()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create receiver first
    receiver = Receiver(
        env, args.receiver_delay, None, event_logger
    )
    
    # Create sender
    sender = Sender(
        env, args.total_packets, args.timeout, args.sender_delay,
        None, event_logger
    )
    
    # Create subnets (channels) with proper connections
    forward_subnet = Subnet(
        env, 'forward_subnet', 'forward', 
        args.seed, args.channel_delay, event_logger, receiver
    )
    backward_subnet = Subnet(
        env, 'backward_subnet', 'backward', 
        args.seed, args.channel_delay, event_logger, sender
    )
    
    # Update sender and receiver with subnet references
    sender.forward_subnet = forward_subnet
    receiver.backward_subnet = backward_subnet
    
    # Run simulation
    env.run(until=args.simulate_time)
    
    # Log completion to stderr
    logging.info(f"Simulation completed. Time: {env.now} ms")


if __name__ == '__main__':
    main()