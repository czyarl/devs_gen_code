#!/usr/bin/env python3
"""
Dropbox-like synchronization simulation using Alternating Bit Protocol (ABP).
Two independent ABP loops: Upload (Sender -> Server) and Download (Server -> Receiver).
"""

import argparse
import sys
import json
import logging
from collections import deque
from typing import Optional, Dict, Any
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
    def __init__(self, seq: int, bit: int):
        self.seq = seq
        self.bit = bit
    
    def __repr__(self):
        return f"Packet(seq={self.seq}, bit={self.bit})"


class EventLogger:
    """Handles JSONL event logging to stdout."""
    def __init__(self):
        self.events = []
    
    def log(self, timestamp_ms: float, model: str, event_type: str, val: Dict[str, Any]):
        """Log an event to stdout."""
        event = {
            "timestamp_ms": timestamp_ms,
            "model": model,
            "type": event_type,
            "val": val
        }
        print(json.dumps(event))
        self.events.append(event)
    
    def log_control_cmd(self, timestamp_ms: float, added: int, total_remaining: int):
        self.log(timestamp_ms, "sender", "control_cmd", {"added": added, "total_remaining": total_remaining})
    
    def log_download_valve_change(self, timestamp_ms: float, allowed: bool):
        self.log(timestamp_ms, "server_sender", "download_valve_change", {"allowed": allowed})
    
    def log_preparation_started(self, timestamp_ms: float, duration: int = 10000):
        self.log(timestamp_ms, "sender", "preparation_started", {"duration": duration})
    
    def log_packet_sent(self, timestamp_ms: float, seq: int, bit: int, is_retry: bool):
        self.log(timestamp_ms, "sender", "packet_sent", {"seq": seq, "bit": bit, "is_retry": is_retry})
    
    def log_ack_received(self, timestamp_ms: float, bit: int):
        self.log(timestamp_ms, "sender", "ack_received", {"bit": bit})
    
    def log_timeout(self, timestamp_ms: float, seq: int):
        self.log(timestamp_ms, "sender", "timeout", {"seq": seq})
    
    def log_packet_received(self, timestamp_ms: float, seq: int, bit: int):
        self.log(timestamp_ms, "server_receiver", "packet_received", {"seq": seq, "bit": bit})
    
    def log_ack_sent_to_sender(self, timestamp_ms: float, bit: int):
        self.log(timestamp_ms, "server_receiver", "ack_sent_to_sender", {"bit": bit})
    
    def log_packet_forwarded(self, timestamp_ms: float, seq: int, bit: int):
        self.log(timestamp_ms, "server_sender", "packet_forwarded", {"seq": seq, "bit": bit})
    
    def log_ack_received_from_receiver(self, timestamp_ms: float, bit: int):
        self.log(timestamp_ms, "server_sender", "ack_received_from_receiver", {"bit": bit})
    
    def log_processing_started(self, timestamp_ms: float, seq: int, duration: int = 10000):
        self.log(timestamp_ms, "receiver", "processing_started", {"seq": seq, "duration": duration})
    
    def log_ack_sent(self, timestamp_ms: float, bit: int):
        self.log(timestamp_ms, "receiver", "ack_sent", {"bit": bit})


class Subnet:
    """Reliable FIFO channel with fixed delay."""
    def __init__(self, env: simpy.Environment, name: str, delay: float, logger: EventLogger):
        self.env = env
        self.name = name
        self.delay = delay
        self.logger = logger
        self.store = simpy.Store(env)
    
    def send(self, packet):
        """Send a packet through the subnet."""
        yield self.env.timeout(self.delay)
        yield self.store.put(packet)
    
    def receive(self):
        """Receive a packet from the subnet."""
        return (yield self.store.get())


class Sender:
    """Uploads packets to server using ABP."""
    def __init__(self, env: simpy.Environment, subnet_a1: Subnet, subnet_a2: Subnet, logger: EventLogger):
        self.env = env
        self.subnet_a1 = subnet_a1
        self.subnet_a2 = subnet_a2
        self.logger = logger
        self.total_packets_to_send = 0
        self.packets_remaining = 0
        self.current_seq = 1
        self.current_bit = 0
        self.waiting_for_ack = False
        self.current_packet = None
        self.ack_timeout = 20.0  # seconds
        self.timeout_event = None
    
    def add_packets(self, n: int):
        """Add packets to upload queue."""
        was_idle = self.total_packets_to_send == 0
        self.total_packets_to_send += n
        self.packets_remaining += n
        self.logger.log_control_cmd(self.env.now * 1000, n, self.packets_remaining)
        
        if was_idle and n > 0:
            self.env.process(self.upload_loop())
    
    def upload_loop(self):
        """Main upload loop using ABP."""
        while self.packets_remaining > 0:
            # Preparation phase (10s)
            self.logger.log_preparation_started(self.env.now * 1000)
            yield self.env.timeout(10.0)
            
            # Send packet
            self.current_packet = Packet(self.current_seq, self.current_bit)
            self.waiting_for_ack = True
            self.logger.log_packet_sent(self.env.now * 1000, self.current_seq, self.current_bit, False)
            
            # Send through subnet
            self.env.process(self.subnet_a1.send(self.current_packet))
            
            # Start timeout timer
            self.timeout_event = self.env.process(self.timeout_handler())
            
            # Wait for ACK
            ack = yield self.subnet_a2.receive()
            
            # Cancel timeout if ACK received
            if self.timeout_event.is_alive:
                self.timeout_event.interrupt()
            
            # Process ACK
            self.logger.log_ack_received(self.env.now * 1000, ack)
            
            if ack == self.current_bit:
                # Correct ACK received
                self.current_bit = 1 - self.current_bit
                self.current_seq += 1
                self.packets_remaining -= 1
                self.waiting_for_ack = False
            # If wrong bit, it's a duplicate ACK, just retry (handled by timeout)
    
    def timeout_handler(self):
        """Handle ACK timeout."""
        try:
            yield self.env.timeout(self.ack_timeout)
            # Timeout occurred
            self.logger.log_timeout(self.env.now * 1000, self.current_seq)
            
            # Retransmit
            self.logger.log_packet_sent(self.env.now * 1000, self.current_seq, self.current_bit, True)
            self.env.process(self.subnet_a1.send(self.current_packet))
            
            # Restart timeout
            self.timeout_event = self.env.process(self.timeout_handler())
        except simpy.Interrupt:
            # ACK received, cancel timeout
            pass


class ServerReceiver:
    """Receives packets from Sender, processes them, and sends ACKs."""
    def __init__(self, env: simpy.Environment, subnet_a1: Subnet, subnet_a2: Subnet, 
                 storage_queue: deque, logger: EventLogger):
        self.env = env
        self.subnet_a1 = subnet_a1
        self.subnet_a2 = subnet_a2
        self.storage_queue = storage_queue
        self.logger = logger
        self.expected_bit = 0
    
    def receive_loop(self):
        """Main receive loop."""
        while True:
            # Receive packet
            packet = yield self.subnet_a1.receive()
            self.logger.log_packet_received(self.env.now * 1000, packet.seq, packet.bit)
            
            # Processing delay (3s)
            yield self.env.timeout(3.0)
            
            # Check bit and send ACK
            if packet.bit == self.expected_bit:
                # New packet
                self.storage_queue.append(packet)
                self.logger.log_ack_sent_to_sender(self.env.now * 1000, packet.bit)
                self.env.process(self.subnet_a2.send(packet.bit))
                self.expected_bit = 1 - self.expected_bit
            else:
                # Duplicate packet, resend previous ACK
                prev_bit = 1 - self.expected_bit
                self.logger.log_ack_sent_to_sender(self.env.now * 1000, prev_bit)
                self.env.process(self.subnet_a2.send(prev_bit))


class ServerSender:
    """Forwards packets from storage to Receiver using ABP."""
    def __init__(self, env: simpy.Environment, subnet_b1: Subnet, subnet_b2: Subnet,
                 storage_queue: deque, logger: EventLogger):
        self.env = env
        self.subnet_b1 = subnet_b1
        self.subnet_b2 = subnet_b2
        self.storage_queue = storage_queue
        self.logger = logger
        self.download_allowed = False
        self.current_seq = 1
        self.current_bit = 0
        self.waiting_for_ack = False
        self.current_packet = None
        self.ack_timeout = 20.0
        self.timeout_event = None
        self.active = False
    
    def set_download_allowed(self, allowed: bool):
        """Set download permission."""
        self.download_allowed = allowed
        self.logger.log_download_valve_change(self.env.now * 1000, allowed)
        
        if allowed and not self.active:
            self.active = True
            self.env.process(self.download_loop())
    
    def download_loop(self):
        """Main download loop using ABP."""
        while True:
            # Wait until download is allowed and we have packets
            while not (self.download_allowed and self.storage_queue):
                if not self.download_allowed:
                    self.active = False
                    return  # Exit the loop when download is disabled
                yield self.env.timeout(0.1)  # Small delay to avoid busy waiting
            
            # Get packet from storage
            self.current_packet = self.storage_queue.popleft()
            self.waiting_for_ack = True
            
            # Forward packet
            self.logger.log_packet_forwarded(self.env.now * 1000, self.current_packet.seq, self.current_packet.bit)
            self.env.process(self.subnet_b1.send(self.current_packet))
            
            # Start timeout timer
            self.timeout_event = self.env.process(self.timeout_handler())
            
            # Wait for ACK
            ack = yield self.subnet_b2.receive()
            
            # Cancel timeout if ACK received
            if self.timeout_event.is_alive:
                self.timeout_event.interrupt()
            
            # Process ACK
            self.logger.log_ack_received_from_receiver(self.env.now * 1000, ack)
            
            if ack == self.current_packet.bit:
                # Correct ACK received
                self.current_bit = 1 - self.current_bit
                self.current_seq += 1
                self.waiting_for_ack = False
            # If wrong bit, it's a duplicate ACK, just retry (handled by timeout)
    
    def timeout_handler(self):
        """Handle ACK timeout."""
        try:
            yield self.env.timeout(self.ack_timeout)
            # Timeout occurred - retransmit
            self.logger.log_packet_forwarded(self.env.now * 1000, self.current_packet.seq, self.current_packet.bit)
            self.env.process(self.subnet_b1.send(self.current_packet))
            
            # Restart timeout
            self.timeout_event = self.env.process(self.timeout_handler())
        except simpy.Interrupt:
            # ACK received, cancel timeout
            pass


class Receiver:
    """Receives packets from Server, processes them, and sends ACKs."""
    def __init__(self, env: simpy.Environment, subnet_b1: Subnet, subnet_b2: Subnet, logger: EventLogger):
        self.env = env
        self.subnet_b1 = subnet_b1
        self.subnet_b2 = subnet_b2
        self.logger = logger
    
    def receive_loop(self):
        """Main receive loop."""
        while True:
            # Receive packet
            packet = yield self.subnet_b1.receive()
            
            # Processing phase (10s)
            self.logger.log_processing_started(self.env.now * 1000, packet.seq)
            yield self.env.timeout(10.0)
            
            # Send ACK
            self.logger.log_ack_sent(self.env.now * 1000, packet.bit)
            self.env.process(self.subnet_b2.send(packet.bit))


def parse_time(time_str: str) -> float:
    """Parse time string to seconds."""
    parts = time_str.split(':')
    if len(parts) == 3:
        # HH:MM:SS
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 4:
        # HH:MM:SS:mmm
        h, m, s, ms = parts
        return int(h) * 3600 + int(m) * 60 + int(s) + float(ms) / 1000
    else:
        raise ValueError(f"Invalid time format: {time_str}")


def parse_stdin_commands(env: simpy.Environment, sender: Sender, server_sender: ServerSender):
    """Parse commands from stdin and schedule them."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        
        parts = line.split()
        if len(parts) != 3:
            logger.warning(f"Invalid command format: {line}")
            continue
        
        time_str, cmd_type, value = parts
        time = parse_time(time_str)
        
        def schedule_command(t=time, cmd=cmd_type, val=value):
            if cmd == "control":
                sender.add_packets(int(val))
            elif cmd == "request":
                server_sender.set_download_allowed(int(val) == 1)
            else:
                logger.warning(f"Unknown command type: {cmd}")
        
        env.process(schedule_command())


def main():
    """Main simulation entry point."""
    parser = argparse.ArgumentParser(description="Dropbox-like synchronization simulation")
    parser.add_argument("--simulation_time", type=float, default=10000000.0,
                        help="Simulation duration in milliseconds (simulation time)")
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    logger_obj = EventLogger()
    
    # Create subnets (3s delay each)
    subnet_a1 = Subnet(env, "A1", 3.0, logger_obj)  # Sender -> Server
    subnet_a2 = Subnet(env, "A2", 3.0, logger_obj)  # Server -> Sender
    subnet_b1 = Subnet(env, "B1", 3.0, logger_obj)  # Server -> Receiver
    subnet_b2 = Subnet(env, "B2", 3.0, logger_obj)  # Receiver -> Server
    
    # Create storage queue
    storage_queue = deque()
    
    # Create entities
    sender = Sender(env, subnet_a1, subnet_a2, logger_obj)
    server_receiver = ServerReceiver(env, subnet_a1, subnet_a2, storage_queue, logger_obj)
    server_sender = ServerSender(env, subnet_b1, subnet_b2, storage_queue, logger_obj)
    receiver = Receiver(env, subnet_b1, subnet_b2, logger_obj)
    
    # Start entity processes
    env.process(server_receiver.receive_loop())
    env.process(receiver.receive_loop())
    
    # Parse stdin commands
    parse_stdin_commands(env, sender, server_sender)
    
    # Run simulation
    sim_time_seconds = args.simulation_time / 1000.0
    logger.info(f"Starting simulation for {sim_time_seconds} seconds (simulation time)")
    env.run(until=sim_time_seconds)
    logger.info("Simulation completed")


if __name__ == "__main__":
    main()
