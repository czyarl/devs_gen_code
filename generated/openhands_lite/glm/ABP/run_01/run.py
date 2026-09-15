#!/usr/bin/env python3
"""
Alternating Bit Protocol (ABP) Simulation with Deterministic Noise
"""

import argparse
import sys
import json
import logging
import simpy

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


class EventLogger:
    """Handles logging of simulation events to stdout in JSONL format."""
    
    def __init__(self):
        pass
    
    def log(self, time, entity, event, payload):
        """Log an event to stdout."""
        record = {
            "time": round(time, 2),
            "entity": entity,
            "event": event,
            "payload": payload
        }
        print(json.dumps(record))
    
    def log_sender_delay_start(self, time, duration):
        """Log sender preparation delay start."""
        self.log(time, "sender", "delay_start", {
            "type": "preparation",
            "duration": duration
        })
    
    def log_sender_packet_sent(self, time, seq_num, bit, is_retry):
        """Log packet sent from sender."""
        self.log(time, "sender", "packet_sent", {
            "seq_num": seq_num,
            "bit": bit,
            "is_retry": is_retry
        })
    
    def log_sender_ack_received(self, time, ack_bit, is_valid):
        """Log ACK received at sender."""
        self.log(time, "sender", "ack_received", {
            "ack_bit": ack_bit,
            "is_valid": is_valid
        })
    
    def log_receiver_delay_start(self, time, duration):
        """Log receiver processing delay start."""
        self.log(time, "receiver", "delay_start", {
            "type": "processing",
            "duration": duration
        })
    
    def log_receiver_packet_received(self, time, seq_num, bit):
        """Log packet received at receiver."""
        self.log(time, "receiver", "packet_received", {
            "seq_num": seq_num,
            "bit": bit
        })
    
    def log_subnet_packet_get(self, time, behavior, channel, noise_value):
        """Log packet fate determination at subnet."""
        self.log(time, "subnet", "packet_get", {
            "behavior": behavior,
            "channel": channel,
            "noise_value": noise_value
        })


class Subnet:
    """Represents a transmission channel with deterministic noise."""
    
    def __init__(self, env, name, channel_type, seed, channel_delay, event_logger):
        self.env = env
        self.name = name
        self.channel_type = channel_type  # "forward" or "backward"
        self.noise_level = seed
        self.channel_delay = channel_delay
        self.event_logger = event_logger
        self.output_pipe = simpy.Store(env)
    
    def calculate_noise(self):
        """Calculate new noise level using LCG formula."""
        new_noise = (17 * self.noise_level + 11) % 100
        self.noise_level = new_noise
        return new_noise
    
    def transmit(self, packet):
        """Transmit a packet through the channel."""
        current_time = self.env.now
        noise_value = self.calculate_noise()
        
        # Determine packet fate
        if noise_value < 10:
            behavior = "drop"
            self.event_logger.log_subnet_packet_get(
                current_time, behavior, self.channel_type, noise_value
            )
            # Packet is dropped, nothing to deliver
            return
        else:
            behavior = "pass"
            self.event_logger.log_subnet_packet_get(
                current_time, behavior, self.channel_type, noise_value
            )
            # Wait for channel delay then deliver
            yield self.env.timeout(self.channel_delay)
            yield self.output_pipe.put(packet)


class Sender:
    """Implements the sender side of ABP."""
    
    def __init__(self, env, total_packets, timeout, sender_delay, event_logger, 
                 forward_subnet, backward_subnet):
        self.env = env
        self.total_packets = total_packets
        self.timeout = timeout
        self.sender_delay = sender_delay
        self.event_logger = event_logger
        self.forward_subnet = forward_subnet
        self.backward_subnet = backward_subnet
        
        self.current_seq = 1
        self.current_bit = 0
        self.packets_sent = 0
        self.ack_received = False
        self.timer_process = None
        self.waiting_for_ack = False
    
    def start_timer(self):
        """Start the retransmission timer."""
        if self.timer_process is not None:
            self.timer_process.interrupt()
        
        def timer():
            try:
                yield self.env.timeout(self.timeout)
                # Timer expired, retransmit
                if self.waiting_for_ack:
                    logger.info(f"Timer expired at {self.env.now}, retransmitting packet {self.current_seq}")
                    self.env.process(self.send_packet(is_retry=True))
            except simpy.Interrupt:
                # Timer was interrupted by ACK
                pass
        
        self.timer_process = self.env.process(timer())
    
    def send_packet(self, is_retry=False):
        """Send a packet to the receiver."""
        if not is_retry:
            # Preparation delay only for new packets
            self.event_logger.log_sender_delay_start(self.env.now, self.sender_delay)
            yield self.env.timeout(self.sender_delay)
        
        # Create packet
        packet = {
            "seq_num": self.current_seq,
            "bit": self.current_bit
        }
        
        # Log packet sent
        self.event_logger.log_sender_packet_sent(
            self.env.now, self.current_seq, self.current_bit, is_retry
        )
        
        # Send through forward subnet
        self.env.process(self.forward_subnet.transmit(packet))
        
        # Start timer
        self.waiting_for_ack = True
        self.start_timer()
    
    def receive_ack(self):
        """Receive ACK from backward subnet."""
        while True:
            ack = yield self.backward_subnet.output_pipe.get()
            current_time = self.env.now
            
            # Validate ACK
            is_valid = (ack["bit"] == self.current_bit)
            self.event_logger.log_sender_ack_received(
                current_time, ack["bit"], is_valid
            )
            
            if is_valid and self.waiting_for_ack:
                # Valid ACK received
                self.waiting_for_ack = False
                if self.timer_process is not None:
                    self.timer_process.interrupt()
                
                # Move to next packet
                self.packets_sent += 1
                if self.packets_sent < self.total_packets:
                    self.current_seq += 1
                    self.current_bit = 1 - self.current_bit  # Toggle bit
                    self.env.process(self.send_packet(is_retry=False))
    
    def run(self):
        """Main sender process."""
        # Start ACK receiver
        self.env.process(self.receive_ack())
        
        # Send first packet
        if self.total_packets > 0:
            self.env.process(self.send_packet(is_retry=False))


class Receiver:
    """Implements the receiver side of ABP."""
    
    def __init__(self, env, receiver_delay, event_logger, forward_subnet, backward_subnet):
        self.env = env
        self.receiver_delay = receiver_delay
        self.event_logger = event_logger
        self.forward_subnet = forward_subnet
        self.backward_subnet = backward_subnet
        
        self.buffer = None
        self.buffer_capacity = 1
        self.is_busy = False
    
    def receive_packet(self):
        """Receive packets from forward subnet."""
        while True:
            packet = yield self.forward_subnet.output_pipe.get()
            
            if self.is_busy:
                # Buffer is full, drop this packet
                logger.info(f"Receiver busy at {self.env.now}, dropping packet {packet['seq_num']}")
                continue
            
            # Store in buffer
            self.buffer = packet
            self.is_busy = True
            
            # Start processing delay
            self.event_logger.log_receiver_delay_start(self.env.now, self.receiver_delay)
            yield self.env.timeout(self.receiver_delay)
            
            # Process packet
            self.event_logger.log_receiver_packet_received(
                self.env.now, packet["seq_num"], packet["bit"]
            )
            
            # Send ACK
            ack = {"bit": packet["bit"]}
            self.env.process(self.backward_subnet.transmit(ack))
            
            # Clear buffer
            self.buffer = None
            self.is_busy = False


def main():
    """Main simulation entry point."""
    parser = argparse.ArgumentParser(
        description="Alternating Bit Protocol Simulation with Deterministic Noise"
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
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create event logger
    event_logger = EventLogger()
    
    # Create subnets (channels)
    forward_subnet = Subnet(
        env, "Subnet1", "forward", args.seed, args.channel_delay, event_logger
    )
    backward_subnet = Subnet(
        env, "Subnet2", "backward", args.seed, args.channel_delay, event_logger
    )
    
    # Create sender and receiver
    sender = Sender(
        env, args.total_packets, args.timeout, args.sender_delay,
        event_logger, forward_subnet, backward_subnet
    )
    receiver = Receiver(
        env, args.receiver_delay, event_logger, forward_subnet, backward_subnet
    )
    
    # Start sender and receiver processes
    env.process(sender.run())
    env.process(receiver.receive_packet())
    
    # Run simulation
    logger.info(f"Starting simulation for {args.simulate_time}ms")
    env.run(until=args.simulate_time)
    logger.info(f"Simulation completed at {env.now}ms")


if __name__ == "__main__":
    main()
