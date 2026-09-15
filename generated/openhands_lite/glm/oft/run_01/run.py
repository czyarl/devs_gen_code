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


class ACK:
    """Acknowledgment packet with alternating bit."""
    
    def __init__(self, bit: int):
        self.bit = bit
    
    def __repr__(self):
        return f"ACK(bit={self.bit})"


class Subnet:
    """Reliable FIFO channel with fixed delay."""
    
    def __init__(self, env: simpy.Environment, name: str, delay: float, 
                 output_queue: simpy.Store):
        self.env = env
        self.name = name
        self.delay = delay
        self.output_queue = output_queue
        self.input_queue = simpy.Store(env)
        self.env.process(self.run())
    
    def run(self):
        """Process packets through the subnet with delay."""
        while True:
            packet = yield self.input_queue.get()
            yield self.env.timeout(self.delay)
            yield self.output_queue.put(packet)
    
    def send(self, packet):
        """Send a packet through the subnet."""
        self.env.process(self._send(packet))
    
    def _send(self, packet):
        """Internal send method."""
        yield self.input_queue.put(packet)


class Sender:
    """Uploads packets to server using ABP."""
    
    def __init__(self, env: simpy.Environment, subnet_to_server: Subnet,
                 subnet_from_server: Subnet):
        self.env = env
        self.subnet_to_server = subnet_to_server
        self.subnet_from_server = subnet_from_server
        
        self.total_packets_to_send = 0
        self.packets_remaining = 0
        self.current_seq = 1
        self.current_bit = 0
        self.is_busy = False
        self.waiting_for_ack = False
        self.ack_timeout_event = None
        
        self.env.process(self.run())
        self.env.process(self.ack_listener())
    
    def add_packets(self, count: int):
        """Add packets to upload queue."""
        self.total_packets_to_send += count
        self.packets_remaining += count
        self._log_control_cmd(count, self.packets_remaining)
        
        if not self.is_busy and self.packets_remaining > 0:
            self.is_busy = True
            self.env.process(self.send_next_packet())
    
    def _log_control_cmd(self, added: int, total_remaining: int):
        """Log control command event."""
        event = {
            "timestamp_ms": self.env.now,
            "model": "sender",
            "type": "control_cmd",
            "val": {"added": added, "total_remaining": total_remaining}
        }
        print(json.dumps(event))
    
    def run(self):
        """Main sender process."""
        while True:
            yield self.env.timeout(1)
    
    def ack_listener(self):
        """Listen for ACKs from server."""
        while True:
            ack = yield self.subnet_from_server.input_queue.get()
            self._log_ack_received(ack.bit)
            
            if self.waiting_for_ack and ack.bit == self.current_bit:
                # Correct ACK received
                if self.ack_timeout_event is not None:
                    self.ack_timeout_event.cancel()
                    self.ack_timeout_event = None
                
                self.waiting_for_ack = False
                self.current_bit = 1 - self.current_bit
                self.current_seq += 1
                self.packets_remaining -= 1
                
                if self.packets_remaining > 0:
                    self.env.process(self.send_next_packet())
                else:
                    self.is_busy = False
    
    def _log_ack_received(self, bit: int):
        """Log ACK received event."""
        event = {
            "timestamp_ms": self.env.now,
            "model": "sender",
            "type": "ack_received",
            "val": {"bit": bit}
        }
        print(json.dumps(event))
    
    def send_next_packet(self):
        """Send next packet with preparation delay."""
        if self.packets_remaining <= 0:
            self.is_busy = False
            return
        
        self._log_preparation_started(10000)
        yield self.env.timeout(10000)
        
        is_retry = False
        self._log_packet_sent(self.current_seq, self.current_bit, is_retry)
        self.subnet_to_server.send(Packet(self.current_seq, self.current_bit))
        self.waiting_for_ack = True
        
        # Start timeout timer
        self.ack_timeout_event = self.env.event()
        self.env.process(self._timeout_handler(self.current_seq))
    
    def _log_preparation_started(self, duration: int):
        """Log preparation started event."""
        event = {
            "timestamp_ms": self.env.now,
            "model": "sender",
            "type": "preparation_started",
            "val": {"duration": duration}
        }
        print(json.dumps(event))
    
    def _log_packet_sent(self, seq: int, bit: int, is_retry: bool):
        """Log packet sent event."""
        event = {
            "timestamp_ms": self.env.now,
            "model": "sender",
            "type": "packet_sent",
            "val": {"seq": seq, "bit": bit, "is_retry": is_retry}
        }
        print(json.dumps(event))
    
    def _timeout_handler(self, seq: int):
        """Handle ACK timeout."""
        try:
            yield self.ack_timeout_event | self.env.timeout(20000)
            if self.ack_timeout_event.triggered:
                return  # ACK received, timeout cancelled
        except simpy.Interrupt:
            return
        
        # Timeout occurred
        if self.waiting_for_ack:
            self._log_timeout(seq)
            self._log_packet_sent(self.current_seq, self.current_bit, True)
            self.subnet_to_server.send(Packet(self.current_seq, self.current_bit))
            self.env.process(self._timeout_handler(seq))
    
    def _log_timeout(self, seq: int):
        """Log timeout event."""
        event = {
            "timestamp_ms": self.env.now,
            "model": "sender",
            "type": "timeout",
            "val": {"seq": seq}
        }
        print(json.dumps(event))


class ServerReceiver:
    """Receives packets from sender, processes them, and stores in queue."""
    
    def __init__(self, env: simpy.Environment, subnet_from_sender: Subnet,
                 subnet_to_sender: Subnet, storage_queue: deque):
        self.env = env
        self.subnet_from_sender = subnet_from_sender
        self.subnet_to_sender = subnet_to_sender
        self.storage_queue = storage_queue
        self.expected_bit = 0
        self.env.process(self.run())
    
    def run(self):
        """Process incoming packets."""
        while True:
            packet = yield self.subnet_from_sender.input_queue.get()
            self._log_packet_received(packet.seq, packet.bit)
            
            # 3s processing delay
            yield self.env.timeout(3000)
            
            if packet.bit == self.expected_bit:
                # New packet
                self.storage_queue.append(packet)
                self.subnet_to_sender.send(ACK(packet.bit))
                self._log_ack_sent_to_sender(packet.bit)
                self.expected_bit = 1 - self.expected_bit
            else:
                # Duplicate packet, resend previous ACK
                self.subnet_to_sender.send(ACK(1 - self.expected_bit))
                self._log_ack_sent_to_sender(1 - self.expected_bit)
    
    def _log_packet_received(self, seq: int, bit: int):
        """Log packet received event."""
        event = {
            "timestamp_ms": self.env.now,
            "model": "server_receiver",
            "type": "packet_received",
            "val": {"seq": seq, "bit": bit}
        }
        print(json.dumps(event))
    
    def _log_ack_sent_to_sender(self, bit: int):
        """Log ACK sent to sender event."""
        event = {
            "timestamp_ms": self.env.now,
            "model": "server_receiver",
            "type": "ack_sent_to_sender",
            "val": {"bit": bit}
        }
        print(json.dumps(event))


class ServerSender:
    """Sends packets from storage queue to receiver using ABP."""
    
    def __init__(self, env: simpy.Environment, subnet_to_receiver: Subnet,
                 subnet_from_receiver: Subnet, storage_queue: deque):
        self.env = env
        self.subnet_to_receiver = subnet_to_receiver
        self.subnet_from_receiver = subnet_from_receiver
        self.storage_queue = storage_queue
        
        self.download_allowed = False
        self.current_packet: Optional[Packet] = None
        self.waiting_for_ack = False
        self.ack_timeout_event = None
        
        self.env.process(self.run())
        self.env.process(self.ack_listener())
    
    def set_download_allowed(self, allowed: bool):
        """Set download permission."""
        self.download_allowed = allowed
        self._log_download_valve_change(allowed)
    
    def _log_download_valve_change(self, allowed: bool):
        """Log download valve change event."""
        event = {
            "timestamp_ms": self.env.now,
            "model": "server_sender",
            "type": "download_valve_change",
            "val": {"allowed": allowed}
        }
        print(json.dumps(event))
    
    def run(self):
        """Main server sender process."""
        while True:
            if (self.download_allowed and 
                self.storage_queue and 
                not self.waiting_for_ack):
                packet = self.storage_queue.popleft()
                self.current_packet = packet
                self._log_packet_forwarded(packet.seq, packet.bit)
                self.subnet_to_receiver.send(packet)
                self.waiting_for_ack = True
                self.env.process(self._timeout_handler(packet.seq))
            
            yield self.env.timeout(1)
    
    def _log_packet_forwarded(self, seq: int, bit: int):
        """Log packet forwarded event."""
        event = {
            "timestamp_ms": self.env.now,
            "model": "server_sender",
            "type": "packet_forwarded",
            "val": {"seq": seq, "bit": bit}
        }
        print(json.dumps(event))
    
    def ack_listener(self):
        """Listen for ACKs from receiver."""
        while True:
            ack = yield self.subnet_from_receiver.input_queue.get()
            self._log_ack_received_from_receiver(ack.bit)
            
            if self.waiting_for_ack and self.current_packet and ack.bit == self.current_packet.bit:
                # Correct ACK received
                if self.ack_timeout_event is not None:
                    self.ack_timeout_event.cancel()
                    self.ack_timeout_event = None
                
                self.waiting_for_ack = False
                self.current_packet = None
    
    def _log_ack_received_from_receiver(self, bit: int):
        """Log ACK received from receiver event."""
        event = {
            "timestamp_ms": self.env.now,
            "model": "server_sender",
            "type": "ack_received_from_receiver",
            "val": {"bit": bit}
        }
        print(json.dumps(event))
    
    def _timeout_handler(self, seq: int):
        """Handle ACK timeout."""
        try:
            self.ack_timeout_event = self.env.event()
            yield self.ack_timeout_event | self.env.timeout(20000)
            if self.ack_timeout_event.triggered:
                return  # ACK received, timeout cancelled
        except simpy.Interrupt:
            return
        
        # Timeout occurred
        if self.waiting_for_ack and self.current_packet:
            self._log_packet_forwarded(self.current_packet.seq, self.current_packet.bit)
            self.subnet_to_receiver.send(self.current_packet)
            self.env.process(self._timeout_handler(seq))


class Receiver:
    """Receives packets from server, processes them, and sends ACKs."""
    
    def __init__(self, env: simpy.Environment, subnet_from_server: Subnet,
                 subnet_to_server: Subnet):
        self.env = env
        self.subnet_from_server = subnet_from_server
        self.subnet_to_server = subnet_to_server
        self.env.process(self.run())
    
    def run(self):
        """Process incoming packets."""
        while True:
            packet = yield self.subnet_from_server.input_queue.get()
            self._log_processing_started(packet.seq, 10000)
            
            # 10s processing delay
            yield self.env.timeout(10000)
            
            self._log_ack_sent(packet.bit)
            self.subnet_to_server.send(ACK(packet.bit))
    
    def _log_processing_started(self, seq: int, duration: int):
        """Log processing started event."""
        event = {
            "timestamp_ms": self.env.now,
            "model": "receiver",
            "type": "processing_started",
            "val": {"seq": seq, "duration": duration}
        }
        print(json.dumps(event))
    
    def _log_ack_sent(self, bit: int):
        """Log ACK sent event."""
        event = {
            "timestamp_ms": self.env.now,
            "model": "receiver",
            "type": "ack_sent",
            "val": {"bit": bit}
        }
        print(json.dumps(event))


def parse_time(time_str: str) -> float:
    """Parse time string to milliseconds."""
    parts = time_str.split(':')
    if len(parts) == 3:
        # HH:MM:SS
        hours, minutes, seconds = parts
        return (int(hours) * 3600 + int(minutes) * 60 + float(seconds)) * 1000
    elif len(parts) == 4:
        # HH:MM:SS:mmm
        hours, minutes, seconds, millis = parts
        return (int(hours) * 3600 + int(minutes) * 60 + int(seconds)) * 1000 + int(millis)
    else:
        raise ValueError(f"Invalid time format: {time_str}")


def parse_input_commands(env: simpy.Environment, sender: Sender, 
                         server_sender: ServerSender):
    """Parse input commands from stdin and schedule events."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        
        try:
            parts = line.split()
            if len(parts) != 3:
                logger.warning(f"Invalid input line: {line}")
                continue
            
            time_str, cmd_type, value_str = parts
            time_ms = parse_time(time_str)
            value = int(value_str)
            
            if cmd_type == "control":
                env.process(schedule_control(env, time_ms, sender, value))
            elif cmd_type == "request":
                env.process(schedule_request(env, time_ms, server_sender, value))
            else:
                logger.warning(f"Unknown command type: {cmd_type}")
        
        except Exception as e:
            logger.error(f"Error parsing line '{line}': {e}")


def schedule_control(env: simpy.Environment, time_ms: float, 
                     sender: Sender, value: int):
    """Schedule a control command."""
    yield env.timeout(time_ms)
    sender.add_packets(value)


def schedule_request(env: simpy.Environment, time_ms: float,
                     server_sender: ServerSender, value: int):
    """Schedule a request command."""
    yield env.timeout(time_ms)
    server_sender.set_download_allowed(value == 1)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Dropbox-like synchronization simulation using ABP"
    )
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=10000000.0,
        help="Simulation duration in milliseconds (default: 10000000.0)"
    )
    args = parser.parse_args()
    
    logger.info(f"Starting simulation with duration: {args.simulation_time}ms")
    
    # Create simpy environment
    env = simpy.Environment()
    
    # Create queues for subnets
    sender_to_server_queue = simpy.Store(env)
    server_to_sender_queue = simpy.Store(env)
    server_to_receiver_queue = simpy.Store(env)
    receiver_to_server_queue = simpy.Store(env)
    
    # Create subnets (3s delay = 3000ms)
    subnet_a1 = Subnet(env, "A1", 3000, sender_to_server_queue)
    subnet_a2 = Subnet(env, "A2", 3000, server_to_sender_queue)
    subnet_b1 = Subnet(env, "B1", 3000, server_to_receiver_queue)
    subnet_b2 = Subnet(env, "B2", 3000, receiver_to_server_queue)
    
    # Create storage queue
    storage_queue = deque()
    
    # Create components
    sender = Sender(env, subnet_a1, subnet_a2)
    server_receiver = ServerReceiver(env, subnet_a1, subnet_a2, storage_queue)
    server_sender = ServerSender(env, subnet_b1, subnet_b2, storage_queue)
    receiver = Receiver(env, subnet_b1, subnet_b2)
    
    # Parse and schedule input commands
    parse_input_commands(env, sender, server_sender)
    
    # Run simulation
    logger.info("Running simulation...")
    env.run(until=args.simulation_time)
    logger.info("Simulation completed")


if __name__ == "__main__":
    main()
