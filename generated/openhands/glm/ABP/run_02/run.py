#!/usr/bin/env python3
"""
Alternating Bit Protocol (ABP) Simulation with Deterministic Noise Interference
"""

import argparse
import sys
import json
import logging
import simpy


class Logger:
    """Custom logger for outputting events to stdout in JSONL format."""
    
    def __init__(self):
        pass
    
    def log_event(self, time, entity, event, payload):
        """Log an event in JSONL format."""
        event_record = {
            "time": float(round(time, 2)),
            "entity": entity,
            "event": event,
            "payload": payload
        }
        print(json.dumps(event_record))


class Subnet:
    """Represents a transmission channel with deterministic noise interference."""
    
    def __init__(self, env, name, direction, seed, channel_delay, logger):
        self.env = env
        self.name = name
        self.direction = direction  # "forward" or "backward"
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
                if packet['destination']:
                    packet['destination'].receive_packet(packet)
    
    def send(self, packet):
        """Send a packet through the subnet."""
        self.store.put(packet)


class Sender:
    """Implements the Sender entity with ABP logic."""
    
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
        self.ack_queue = simpy.Store(env)
        
        self.env.process(self.run())
    
    def run(self):
        """Main sender process."""
        while self.packets_sent < self.total_packets:
            # Preparation delay
            self.logger.log_event(
                self.env.now,
                "sender",
                "delay_start",
                {"type": "preparation", "duration": self.sender_delay}
            )
            yield self.env.timeout(self.sender_delay)
            
            # Send packet
            is_retry = self.packets_sent > 0 and self.waiting_for_ack
            packet = {
                'seq_num': self.seq_num,
                'bit': self.current_bit,
                'destination': None
            }
            
            self.logger.log_event(
                self.env.now,
                "sender",
                "packet_sent",
                {"seq_num": self.seq_num, "bit": self.current_bit, "is_retry": is_retry}
            )
            
            self.subnet1.send(packet)
            self.waiting_for_ack = True
            
            # Start timer
            if self.timer_process is not None and self.timer_process.is_alive:
                self.timer_process.interrupt()
            self.timer_process = self.env.process(self.timer())
            
            # Wait for ACK
            ack = yield self.ack_queue.get()
            
            # Validate ACK
            is_valid = ack['bit'] == self.current_bit
            self.logger.log_event(
                self.env.now,
                "sender",
                "ack_received",
                {"ack_bit": ack['bit'], "is_valid": is_valid}
            )
            
            if is_valid:
                # Cancel timer
                if self.timer_process.is_alive:
                    self.timer_process.interrupt()
                
                # Prepare for next packet
                self.packets_sent += 1
                self.seq_num += 1
                self.current_bit = 1 - self.current_bit
                self.waiting_for_ack = False
    
    def timer(self):
        """Timeout timer for retransmission."""
        try:
            yield self.env.timeout(self.timeout)
            # Timer expired, trigger retransmission
            self.ack_queue.put({'bit': 1 - self.current_bit})  # Invalid ACK to trigger retry
        except simpy.Interrupt:
            pass
    
    def receive_packet(self, packet):
        """Receive ACK packet."""
        self.ack_queue.put(packet)


class Receiver:
    """Implements the Receiver entity."""
    
    def __init__(self, env, receiver_delay, subnet2, logger):
        self.env = env
        self.receiver_delay = receiver_delay
        self.subnet2 = subnet2
        self.logger = logger
        
        self.buffer = None
        self.busy = False
        self.packet_queue = simpy.Store(env)
        
        self.env.process(self.run())
    
    def run(self):
        """Main receiver process."""
        while True:
            packet = yield self.packet_queue.get()
            
            # If busy, only keep the first packet
            if self.busy:
                continue
            
            self.busy = True
            self.buffer = packet
            
            # Processing delay
            self.logger.log_event(
                self.env.now,
                "receiver",
                "delay_start",
                {"type": "processing", "duration": self.receiver_delay}
            )
            yield self.env.timeout(self.receiver_delay)
            
            # Process packet
            self.logger.log_event(
                self.env.now,
                "receiver",
                "packet_received",
                {"seq_num": self.buffer['seq_num'], "bit": self.buffer['bit']}
            )
            
            # Send ACK
            ack = {
                'bit': self.buffer['bit'],
                'destination': None
            }
            self.subnet2.send(ack)
            
            # Clear buffer and mark as not busy
            self.buffer = None
            self.busy = False
    
    def receive_packet(self, packet):
        """Receive data packet."""
        self.packet_queue.put(packet)


def main():
    """Main entry point for the simulation."""
    parser = argparse.ArgumentParser(
        description='Alternating Bit Protocol (ABP) Simulation with Deterministic Noise Interference'
    )
    parser.add_argument('--total_packets', type=int, required=True,
                        help='Total number of packets to send')
    parser.add_argument('--seed', type=int, default=42,
                        help='Initialization seed for noise generator (default: 42)')
    parser.add_argument('--timeout', type=int, default=20,
                        help='Sender timeout duration in ms (default: 20)')
    parser.add_argument('--sender_delay', type=int, default=10,
                        help='Sender preparation delay in ms (default: 10)')
    parser.add_argument('--receiver_delay', type=int, default=10,
                        help='Receiver processing delay in ms (default: 10)')
    parser.add_argument('--channel_delay', type=int, default=3,
                        help='Subnet transmission delay in ms (default: 3)')
    parser.add_argument('--simulate_time', type=int, default=1000,
                        help='Total simulation time in ms (default: 1000)')
    
    args = parser.parse_args()
    
    # Setup logging for stderr (debug info)
    logging.basicConfig(
        level=logging.WARNING,
        format='%(asctime)s - %(levelname)s - %(message)s',
        stream=sys.stderr
    )
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create logger for events
    logger = Logger()
    
    # Create subnets
    subnet1 = Subnet(env, "subnet1", "forward", args.seed, args.channel_delay, logger)
    subnet2 = Subnet(env, "subnet2", "backward", args.seed, args.channel_delay, logger)
    
    # Create sender and receiver
    sender = Sender(env, args.total_packets, args.timeout, args.sender_delay, subnet1, logger)
    receiver = Receiver(env, args.receiver_delay, subnet2, logger)
    
    # Connect entities
    subnet1.send = lambda p: subnet1.store.put({**p, 'destination': receiver})
    subnet2.send = lambda p: subnet2.store.put({**p, 'destination': sender})
    
    # Run simulation
    env.run(until=args.simulate_time)


if __name__ == '__main__':
    main()