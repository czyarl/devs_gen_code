#!/usr/bin/env python3
"""
Dropbox-like synchronization simulation using two independent ABP loops.
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
    """Represents a data packet with sequence number and alternating bit."""
    def __init__(self, seq, bit):
        self.seq = seq
        self.bit = bit
    
    def __repr__(self):
        return f"Packet(seq={self.seq}, bit={self.bit})"


class ACK:
    """Represents an ACK with alternating bit."""
    def __init__(self, bit):
        self.bit = bit
    
    def __repr__(self):
        return f"ACK(bit={self.bit})"


def log_event(timestamp_ms, model, event_type, val):
    """Log an event to stdout as JSONL."""
    event = {
        "timestamp_ms": timestamp_ms,
        "model": model,
        "type": event_type,
        "val": val
    }
    print(json.dumps(event))


class Subnet:
    """Reliable FIFO channel with fixed delay."""
    def __init__(self, env, name, delay_ms, log_prefix):
        self.env = env
        self.name = name
        self.delay_ms = delay_ms
        self.log_prefix = log_prefix
        self.queue = simpy.Store(env)
        self.out_channel = None
    
    def set_output(self, channel):
        """Set the output channel."""
        self.out_channel = channel
    
    def send(self, item):
        """Send an item through the subnet."""
        def _deliver():
            yield self.env.timeout(self.delay_ms / 1000.0)
            if self.out_channel:
                self.out_channel.put(item)
        
        self.env.process(_deliver())
    
    def put(self, item):
        """Receive an item and forward it."""
        self.send(item)


class Sender:
    """Uploads packets to the server using ABP protocol."""
    def __init__(self, env, subnet_a1, subnet_a2):
        self.env = env
        self.subnet_a1 = subnet_a1
        self.subnet_a2 = subnet_a2
        self.subnet_a2.set_output(self)
        
        self.total_packets_to_send = 0
        self.packets_remaining = 0
        self.current_seq = 1
        self.current_bit = 0
        self.is_busy = False
        self.waiting_for_ack = False
        self.ack_timeout_event = None
        
        self.input_queue = simpy.Store(env)
        self.ack_queue = simpy.Store(env)
        
        # Start the main process
        self.env.process(self.run())
    
    def add_packets(self, n):
        """Add packets to send."""
        self.total_packets_to_send += n
        self.packets_remaining += n
        log_event(
            self.env.now * 1000,
            "sender",
            "control_cmd",
            {"added": n, "total_remaining": self.packets_remaining}
        )
        # Wake up if idle
        if not self.is_busy and self.packets_remaining > 0:
            self.input_queue.put("wake")
    
    def put(self, item):
        """Receive ACK from subnet."""
        self.ack_queue.put(item)
    
    def run(self):
        """Main sender process."""
        while True:
            # Wait for work or ACK
            if not self.is_busy and self.packets_remaining > 0:
                # Start sending
                yield self.input_queue.get()
            
            if self.packets_remaining > 0 and not self.waiting_for_ack:
                # Preparation phase
                self.is_busy = True
                log_event(
                    self.env.now * 1000,
                    "sender",
                    "preparation_started",
                    {"duration": 10000}
                )
                yield self.env.timeout(10.0)  # 10s preparation
                
                # Send packet
                packet = Packet(self.current_seq, self.current_bit)
                self.waiting_for_ack = True
                log_event(
                    self.env.now * 1000,
                    "sender",
                    "packet_sent",
                    {"seq": self.current_seq, "bit": self.current_bit, "is_retry": False}
                )
                self.subnet_a1.send(packet)
                
                # Start timeout timer
                self.ack_timeout_event = self.env.process(self._timeout_handler())
            
            # Wait for ACK
            if self.waiting_for_ack:
                try:
                    ack = yield self.ack_queue.get()
                    if isinstance(ack, ACK) and ack.bit == self.current_bit:
                        # Correct ACK received
                        if self.ack_timeout_event:
                            self.ack_timeout_event.interrupt()
                            self.ack_timeout_event = None
                        
                        log_event(
                            self.env.now * 1000,
                            "sender",
                            "ack_received",
                            {"bit": ack.bit}
                        )
                        
                        # Update state
                        self.current_seq += 1
                        self.current_bit = 1 - self.current_bit
                        self.packets_remaining -= 1
                        self.waiting_for_ack = False
                        
                        if self.packets_remaining == 0:
                            self.is_busy = False
                except:
                    pass
    
    def _timeout_handler(self):
        """Handle ACK timeout."""
        try:
            yield self.env.timeout(20.0)  # 20s timeout
            # Timeout occurred, retransmit
            log_event(
                self.env.now * 1000,
                "sender",
                "timeout",
                {"seq": self.current_seq}
            )
            packet = Packet(self.current_seq, self.current_bit)
            log_event(
                self.env.now * 1000,
                "sender",
                "packet_sent",
                {"seq": self.current_seq, "bit": self.current_bit, "is_retry": True}
            )
            self.subnet_a1.send(packet)
            # Restart timeout
            self.ack_timeout_event = self.env.process(self._timeout_handler())
        except simpy.Interrupt:
            pass


class ServerReceiver:
    """Receives packets from Sender, processes them, and stores in queue."""
    def __init__(self, env, subnet_a1, subnet_a2, storage_queue):
        self.env = env
        self.subnet_a1 = subnet_a1
        self.subnet_a2 = subnet_a2
        self.storage_queue = storage_queue
        self.subnet_a1.set_output(self)
        
        self.expected_bit = 0
        self.input_queue = simpy.Store(env)
        
        self.env.process(self.run())
    
    def put(self, item):
        """Receive packet from subnet."""
        self.input_queue.put(item)
    
    def run(self):
        """Main server receiver process."""
        while True:
            packet = yield self.input_queue.get()
            
            if isinstance(packet, Packet):
                log_event(
                    self.env.now * 1000,
                    "server_receiver",
                    "packet_received",
                    {"seq": packet.seq, "bit": packet.bit}
                )
                
                # Processing delay
                yield self.env.timeout(3.0)  # 3s processing
                
                if packet.bit == self.expected_bit:
                    # New packet
                    ack = ACK(packet.bit)
                    log_event(
                        self.env.now * 1000,
                        "server_receiver",
                        "ack_sent_to_sender",
                        {"bit": packet.bit}
                    )
                    self.subnet_a2.send(ack)
                    
                    # Store packet
                    self.storage_queue.append(packet)
                    self.expected_bit = 1 - self.expected_bit
                else:
                    # Duplicate packet, resend previous ACK
                    ack = ACK(1 - self.expected_bit)
                    log_event(
                        self.env.now * 1000,
                        "server_receiver",
                        "ack_sent_to_sender",
                        {"bit": ack.bit}
                    )
                    self.subnet_a2.send(ack)


class ServerSender:
    """Sends packets from storage queue to Receiver using ABP protocol."""
    def __init__(self, env, subnet_b1, subnet_b2, storage_queue):
        self.env = env
        self.subnet_b1 = subnet_b1
        self.subnet_b2 = subnet_b2
        self.subnet_b2.set_output(self)
        self.storage_queue = storage_queue
        
        self.download_allowed = False
        self.current_packet = None
        self.current_bit = 0
        self.waiting_for_ack = False
        self.ack_timeout_event = None
        
        self.ack_queue = simpy.Store(env)
        
        self.env.process(self.run())
    
    def set_download_allowed(self, allowed):
        """Set download permission."""
        self.download_allowed = allowed
        log_event(
            self.env.now * 1000,
            "server_sender",
            "download_valve_change",
            {"allowed": allowed}
        )
    
    def put(self, item):
        """Receive ACK from subnet."""
        self.ack_queue.put(item)
    
    def run(self):
        """Main server sender process."""
        while True:
            # Check if we can send
            if (self.download_allowed and 
                self.storage_queue and 
                not self.waiting_for_ack):
                
                # Get packet from queue
                self.current_packet = self.storage_queue.popleft(0)
                self.waiting_for_ack = True
                
                log_event(
                    self.env.now * 1000,
                    "server_sender",
                    "packet_forwarded",
                    {"seq": self.current_packet.seq, "bit": self.current_bit}
                )
                self.subnet_b1.send(self.current_packet)
                
                # Start timeout timer
                self.ack_timeout_event = self.env.process(self._timeout_handler())
            
            # Wait for ACK or state change
            if self.waiting_for_ack:
                try:
                    ack = yield self.ack_queue.get()
                    if isinstance(ack, ACK) and ack.bit == self.current_bit:
                        # Correct ACK received
                        if self.ack_timeout_event:
                            self.ack_timeout_event.interrupt()
                            self.ack_timeout_event = None
                        
                        log_event(
                            self.env.now * 1000,
                            "server_sender",
                            "ack_received_from_receiver",
                            {"bit": ack.bit}
                        )
                        
                        # Update state
                        self.current_bit = 1 - self.current_bit
                        self.current_packet = None
                        self.waiting_for_ack = False
                except:
                    pass
            else:
                # Wait a bit and check again
                yield self.env.timeout(0.1)
    
    def _timeout_handler(self):
        """Handle ACK timeout."""
        try:
            yield self.env.timeout(20.0)  # 20s timeout
            # Timeout occurred, retransmit
            if self.current_packet:
                log_event(
                    self.env.now * 1000,
                    "server_sender",
                    "packet_forwarded",
                    {"seq": self.current_packet.seq, "bit": self.current_bit}
                )
                self.subnet_b1.send(self.current_packet)
                # Restart timeout
                self.ack_timeout_event = self.env.process(self._timeout_handler())
        except simpy.Interrupt:
            pass


class Receiver:
    """Receives packets from Server, processes them, and sends ACK."""
    def __init__(self, env, subnet_b1, subnet_b2):
        self.env = env
        self.subnet_b1 = subnet_b1
        self.subnet_b2 = subnet_b2
        self.subnet_b1.set_output(self)
        
        self.expected_bit = 0
        self.input_queue = simpy.Store(env)
        
        self.env.process(self.run())
    
    def put(self, item):
        """Receive packet from subnet."""
        self.input_queue.put(item)
    
    def run(self):
        """Main receiver process."""
        while True:
            packet = yield self.input_queue.get()
            
            if isinstance(packet, Packet):
                # Processing phase
                log_event(
                    self.env.now * 1000,
                    "receiver",
                    "processing_started",
                    {"seq": packet.seq, "duration": 10000}
                )
                yield self.env.timeout(10.0)  # 10s processing
                
                # Send ACK
                ack = ACK(self.expected_bit)
                log_event(
                    self.env.now * 1000,
                    "receiver",
                    "ack_sent",
                    {"bit": self.expected_bit}
                )
                self.subnet_b2.send(ack)
                
                # Flip expected bit
                self.expected_bit = 1 - self.expected_bit


def parse_time(time_str):
    """Parse time string HH:MM:SS or HH:MM:SS:mmm to seconds."""
    parts = time_str.split(':')
    if len(parts) == 3:
        # HH:MM:SS
        hours, minutes, seconds = map(int, parts)
        return hours * 3600 + minutes * 60 + seconds
    elif len(parts) == 4:
        # HH:MM:SS:mmm
        hours, minutes, seconds, millis = map(int, parts)
        return hours * 3600 + minutes * 60 + seconds + millis / 1000.0
    else:
        raise ValueError(f"Invalid time format: {time_str}")


def read_commands(env, sender, server_sender):
    """Read commands from stdin and schedule them."""
    commands = []
    
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        
        parts = line.split()
        if len(parts) != 3:
            logger.warning(f"Invalid command format: {line}")
            continue
        
        time_str, cmd_type, value = parts
        time_sec = parse_time(time_str)
        
        try:
            value = int(value)
        except ValueError:
            logger.warning(f"Invalid value: {value}")
            continue
        
        commands.append((time_sec, cmd_type, value))
    
    # Sort commands by time
    commands.sort(key=lambda x: x[0])
    
    # Schedule commands
    for time_sec, cmd_type, value in commands:
        def _execute_command(t=type, c=cmd_type, v=value):
            if c == "control":
                sender.add_packets(v)
            elif c == "request":
                server_sender.set_download_allowed(bool(v))
        
        env.process(_schedule_command(env, time_sec, _execute_command))


def _schedule_command(env, time_sec, command_func):
    """Schedule a command to be executed at a specific time."""
    yield env.timeout(time_sec)
    command_func()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Dropbox-like synchronization simulation"
    )
    parser.add_argument(
        '--simulation_time',
        type=float,
        default=10000000.0,
        help='Simulation duration in milliseconds (simulation time)'
    )
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create storage queue (shared between ServerReceiver and ServerSender)
    storage_queue = deque()
    
    # Create subnets (3s delay = 3000ms)
    subnet_a1 = Subnet(env, "A1", 3000, "A1")  # Sender -> Server
    subnet_a2 = Subnet(env, "A2", 3000, "A2")  # Server -> Sender
    subnet_b1 = Subnet(env, "B1", 3000, "B1")  # Server -> Receiver
    subnet_b2 = Subnet(env, "B2", 3000, "B2")  # Receiver -> Server
    
    # Create components
    sender = Sender(env, subnet_a1, subnet_a2)
    server_receiver = ServerReceiver(env, subnet_a1, subnet_a2, storage_queue)
    server_sender = ServerSender(env, subnet_b1, subnet_b2, storage_queue)
    receiver = Receiver(env, subnet_b1, subnet_b2)
    
    # Read and schedule commands from stdin
    read_commands(env, sender, server_sender)
    
    # Run simulation
    simulation_time_sec = args.simulation_time / 1000.0
    logger.info(f"Starting simulation for {simulation_time_sec} seconds (simulation time)")
    env.run(until=simulation_time_sec)
    logger.info("Simulation completed")


if __name__ == "__main__":
    main()
