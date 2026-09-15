#!/usr/bin/env python3
"""
Dropbox-like synchronization simulation using Alternating Bit Protocol (ABP).
Two independent ABP loops: Upload (Sender->Server) and Download (Server->Receiver).
"""

import argparse
import sys
import json
import logging
from collections import deque
import simpy

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


class Packet:
    """Data packet with sequence number and alternating bit."""
    def __init__(self, seq, bit):
        self.seq = seq
        self.bit = bit
    
    def __repr__(self):
        return f"Packet(seq={self.seq}, bit={self.bit})"


class EventLogger:
    """Handles JSONL event logging to stdout."""
    def __init__(self):
        self.events = []
    
    def log(self, timestamp_ms, model, event_type, val):
        """Log an event."""
        event = {
            "timestamp_ms": timestamp_ms,
            "model": model,
            "type": event_type,
            "val": val
        }
        self.events.append(event)
        print(json.dumps(event))
        sys.stdout.flush()


class Subnet:
    """Reliable FIFO channel with fixed delay."""
    def __init__(self, env, name, delay_ms, logger):
        self.env = env
        self.name = name
        self.delay_ms = delay_ms
        self.logger = logger
        self.store = simpy.Store(env)
    
    def send(self, packet, source, dest):
        """Send packet through subnet with delay."""
        yield self.env.timeout(self.delay_ms / 1000.0)
        self.store.put((packet, source, dest))
    
    def get(self):
        """Get packet from subnet (blocking)."""
        return self.store.get()


class Sender:
    """Uploads packets to server using ABP."""
    def __init__(self, env, subnet_out, subnet_in, event_logger):
        self.env = env
        self.subnet_out = subnet_out
        self.subnet_in = subnet_in
        self.event_logger = event_logger
        
        self.total_packets_to_send = 0
        self.packets_remaining = 0
        self.current_seq = 1
        self.current_bit = 0
        self.is_busy = False
        self.waiting_for_ack = False
        self.timeout_process = None
        
        # Start the main process
        self.env.process(self.run())
        self.env.process(self.receive_ack())
    
    def add_packets(self, n):
        """Add packets to upload queue."""
        was_idle = not self.is_busy
        self.total_packets_to_send += n
        self.packets_remaining += n
        
        self.event_logger.log(
            self.env.now * 1000,
            "sender",
            "control_cmd",
            {"added": n, "total_remaining": self.packets_remaining}
        )
        
        if was_idle and self.packets_remaining > 0:
            self.is_busy = True
    
    def run(self):
        """Main sender loop."""
        while True:
            if self.packets_remaining > 0 and not self.waiting_for_ack:
                # Start preparation
                self.event_logger.log(
                    self.env.now * 1000,
                    "sender",
                    "preparation_started",
                    {"duration": 10000}
                )
                yield self.env.timeout(10.0)  # 10s preparation
                
                # Send packet
                is_retry = False
                packet = Packet(self.current_seq, self.current_bit)
                self.event_logger.log(
                    self.env.now * 1000,
                    "sender",
                    "packet_sent",
                    {"seq": packet.seq, "bit": packet.bit, "is_retry": is_retry}
                )
                
                # Send through subnet
                self.env.process(self.subnet_out.send(packet, "sender", "server_receiver"))
                self.waiting_for_ack = True
                
                # Start timeout timer
                self.timeout_process = self.env.process(self._timeout_handler())
            
            yield self.env.timeout(0.1)  # Small delay to prevent busy waiting
    
    def _timeout_handler(self):
        """Handle ACK timeout."""
        try:
            yield self.env.timeout(20.0)  # 20s timeout
            if self.waiting_for_ack:
                # Timeout occurred, retransmit
                self.event_logger.log(
                    self.env.now * 1000,
                    "sender",
                    "timeout",
                    {"seq": self.current_seq}
                )
                
                packet = Packet(self.current_seq, self.current_bit)
                self.event_logger.log(
                    self.env.now * 1000,
                    "sender",
                    "packet_sent",
                    {"seq": packet.seq, "bit": packet.bit, "is_retry": True}
                )
                
                self.env.process(self.subnet_out.send(packet, "sender", "server_receiver"))
                
                # Restart timeout
                self.timeout_process = self.env.process(self._timeout_handler())
        except simpy.Interrupt:
            pass
    
    def receive_ack(self):
        """Receive ACK from server."""
        while True:
            packet, source, dest = yield self.subnet_in.get()
            if dest == "sender" and hasattr(packet, 'bit'):
                self.event_logger.log(
                    self.env.now * 1000,
                    "sender",
                    "ack_received",
                    {"bit": packet.bit}
                )
                
                if packet.bit == self.current_bit:
                    # Correct ACK received
                    if self.timeout_process:
                        self.timeout_process.interrupt()
                    
                    self.waiting_for_ack = False
                    self.current_bit = 1 - self.current_bit  # Flip bit
                    self.current_seq += 1
                    self.packets_remaining -= 1
                    
                    if self.packets_remaining == 0:
                        self.is_busy = False


class ServerReceiver:
    """Receives packets from sender, processes and stores them."""
    def __init__(self, env, subnet_in, subnet_out, storage_queue, queue_size_ref, event_logger):
        self.env = env
        self.subnet_in = subnet_in
        self.subnet_out = subnet_out
        self.storage_queue = storage_queue
        self.queue_size_ref = queue_size_ref  # Reference to queue_size counter
        self.event_logger = event_logger
        
        self.expected_bit = 0
        
        self.env.process(self.run())
    
    def run(self):
        """Main receiver loop."""
        while True:
            packet, source, dest = yield self.subnet_in.get()
            if dest == "server_receiver":
                self.event_logger.log(
                    self.env.now * 1000,
                    "server_receiver",
                    "packet_received",
                    {"seq": packet.seq, "bit": packet.bit}
                )
                
                # 3s processing delay
                yield self.env.timeout(3.0)
                
                if packet.bit == self.expected_bit:
                    # New packet
                    self.storage_queue.put(packet)
                    self.queue_size_ref[0] += 1  # Increment queue size
                    ack_bit = packet.bit
                    self.expected_bit = 1 - self.expected_bit
                else:
                    # Duplicate, resend previous ACK
                    ack_bit = 1 - self.expected_bit
                
                # Send ACK
                ack_packet = Packet(0, ack_bit)
                self.event_logger.log(
                    self.env.now * 1000,
                    "server_receiver",
                    "ack_sent_to_sender",
                    {"bit": ack_bit}
                )
                self.env.process(self.subnet_out.send(ack_packet, "server_receiver", "sender"))


class ServerSender:
    """Sends packets from storage queue to receiver."""
    def __init__(self, env, subnet_out, subnet_in, storage_queue, queue_size_ref, event_logger):
        self.env = env
        self.subnet_out = subnet_out
        self.subnet_in = subnet_in
        self.storage_queue = storage_queue
        self.queue_size_ref = queue_size_ref  # Reference to queue_size counter
        self.event_logger = event_logger
        
        self.download_allowed = False
        self.current_packet = None
        self.current_bit = 0
        self.waiting_for_ack = False
        
        self.env.process(self.run())
        self.env.process(self.receive_ack())
    
    def set_download_allowed(self, allowed):
        """Set download permission."""
        self.download_allowed = allowed
        self.event_logger.log(
            self.env.now * 1000,
            "server_sender",
            "download_valve_change",
            {"allowed": allowed}
        )
    
    def run(self):
        """Main sender loop."""
        while True:
            if (self.download_allowed and 
                not self.waiting_for_ack and 
                self.queue_size_ref[0] > 0):
                
                # Get packet from queue
                self.current_packet = yield self.storage_queue.get()
                self.queue_size_ref[0] -= 1
                
                # Send packet
                self.event_logger.log(
                    self.env.now * 1000,
                    "server_sender",
                    "packet_forwarded",
                    {"seq": self.current_packet.seq, "bit": self.current_bit}
                )
                
                packet = Packet(self.current_packet.seq, self.current_bit)
                self.env.process(self.subnet_out.send(packet, "server_sender", "receiver"))
                self.waiting_for_ack = True
            
            yield self.env.timeout(0.1)
    
    def receive_ack(self):
        """Receive ACK from receiver."""
        while True:
            packet, source, dest = yield self.subnet_in.get()
            if dest == "server_sender" and hasattr(packet, 'bit'):
                self.event_logger.log(
                    self.env.now * 1000,
                    "server_sender",
                    "ack_received_from_receiver",
                    {"bit": packet.bit}
                )
                
                if packet.bit == self.current_bit:
                    self.waiting_for_ack = False
                    self.current_bit = 1 - self.current_bit
                    self.current_packet = None


class Receiver:
    """Receives packets from server, processes and sends ACK."""
    def __init__(self, env, subnet_in, subnet_out, event_logger):
        self.env = env
        self.subnet_in = subnet_in
        self.subnet_out = subnet_out
        self.event_logger = event_logger
        
        self.env.process(self.run())
    
    def run(self):
        """Main receiver loop."""
        while True:
            packet, source, dest = yield self.subnet_in.get()
            if dest == "receiver":
                # Start processing
                self.event_logger.log(
                    self.env.now * 1000,
                    "receiver",
                    "processing_started",
                    {"seq": packet.seq, "duration": 10000}
                )
                
                # 10s processing delay
                yield self.env.timeout(10.0)
                
                # Send ACK
                ack_packet = Packet(0, packet.bit)
                self.event_logger.log(
                    self.env.now * 1000,
                    "receiver",
                    "ack_sent",
                    {"bit": packet.bit}
                )
                self.env.process(self.subnet_out.send(ack_packet, "receiver", "server_sender"))


def parse_time(time_str):
    """Parse time string to milliseconds."""
    parts = time_str.split(':')
    if len(parts) == 3:
        # HH:MM:SS
        h, m, s = parts
        return (int(h) * 3600 + int(m) * 60 + int(s)) * 1000
    elif len(parts) == 4:
        # HH:MM:SS:mmm
        h, m, s, ms = parts
        return (int(h) * 3600 + int(m) * 60 + int(s)) * 1000 + int(ms)
    else:
        raise ValueError(f"Invalid time format: {time_str}")


def schedule_commands(env, sender, server_sender, commands):
    """Schedule control and request commands."""
    for time_str, cmd_type, value in commands:
        time_ms = parse_time(time_str)
        time_sec = time_ms / 1000.0
        
        def execute_command(t=cmd_type, v=value):
            if t == "control":
                sender.add_packets(int(v))
            elif t == "request":
                server_sender.set_download_allowed(int(v) == 1)
        
        env.process(_delayed_execute(env, time_sec, execute_command))


def _delayed_execute(env, delay, func):
    """Execute function after delay."""
    yield env.timeout(delay)
    func()


def main():
    parser = argparse.ArgumentParser(
        description="Dropbox-like synchronization simulation using ABP"
    )
    parser.add_argument(
        '--simulation_time',
        type=float,
        default=10000000.0,
        help='Simulation duration in milliseconds (simulation time)'
    )
    args = parser.parse_args()
    
    # Read commands from stdin
    commands = []
    for line in sys.stdin:
        line = line.strip()
        if line:
            parts = line.split()
            if len(parts) >= 3:
                time_str = parts[0]
                cmd_type = parts[1]
                value = parts[2]
                commands.append((time_str, cmd_type, value))
    
    logger.info(f"Read {len(commands)} commands from stdin")
    
    # Create simulation environment
    env = simpy.Environment()
    event_logger = EventLogger()
    
    # Create storage queue and queue size tracker
    storage_queue = simpy.Store(env)
    queue_size_ref = [0]  # Use list for mutable reference
    
    # Create subnets (3s delay = 3000ms)
    subnet_a1 = Subnet(env, "A1", 3000, event_logger)  # Sender -> Server
    subnet_a2 = Subnet(env, "A2", 3000, event_logger)  # Server -> Sender
    subnet_b1 = Subnet(env, "B1", 3000, event_logger)  # Server -> Receiver
    subnet_b2 = Subnet(env, "B2", 3000, event_logger)  # Receiver -> Server
    
    # Create components
    sender = Sender(env, subnet_a1, subnet_a2, event_logger)
    server_receiver = ServerReceiver(env, subnet_a1, subnet_a2, storage_queue, queue_size_ref, event_logger)
    server_sender = ServerSender(env, subnet_b1, subnet_b2, storage_queue, queue_size_ref, event_logger)
    receiver = Receiver(env, subnet_b1, subnet_b2, event_logger)
    
    # Schedule commands
    schedule_commands(env, sender, server_sender, commands)
    
    # Run simulation
    sim_time_sec = args.simulation_time / 1000.0
    logger.info(f"Starting simulation for {sim_time_sec} seconds (simulation time)")
    env.run(until=sim_time_sec)
    logger.info("Simulation completed")


if __name__ == "__main__":
    main()