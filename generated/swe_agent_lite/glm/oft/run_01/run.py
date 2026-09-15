#!/usr/bin/env python3
"""
Dropbox-like synchronization simulation using Alternating Bit Protocol (ABP).
Two independent ABP loops:
- Loop 1 (Upload): Sender -> SubnetA -> Server
- Loop 2 (Download): Server -> SubnetB -> Receiver
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


class EventLogger:
    """Handles logging events to stdout as JSONL."""
    
    def __init__(self):
        self.events = []
    
    def log(self, timestamp_ms: float, model: str, event_type: str, val: Dict[str, Any]):
        """Log an event."""
        event = {
            "timestamp_ms": timestamp_ms,
            "model": model,
            "type": event_type,
            "val": val
        }
        print(json.dumps(event))
        sys.stdout.flush()


class Packet:
    """Represents a data packet with sequence number and alternating bit."""
    
    def __init__(self, seq: int, bit: int):
        self.seq = seq
        self.bit = bit
    
    def __repr__(self):
        return f"Packet(seq={self.seq}, bit={self.bit})"


class Subnet:
    """Reliable, FIFO, fixed delay channel."""
    
    def __init__(self, env: simpy.Environment, name: str, delay: float, 
                 logger: EventLogger):
        self.env = env
        self.name = name
        self.delay = delay
        self.logger = logger
        self.queue = simpy.Store(env)
        self.in_transit = []
    
    def put(self, packet: Packet, source: str, dest: str):
        """Put a packet into the subnet for transmission."""
        self.in_transit.append((packet, source, dest))
        self.env.process(self._transmit(packet, source, dest))
    
    def _transmit(self, packet: Packet, source: str, dest: str):
        """Simulate transmission delay."""
        yield self.env.timeout(self.delay)
        self.queue.put((packet, source, dest))
        if (packet, source, dest) in self.in_transit:
            self.in_transit.remove((packet, source, dest))
    
    def get(self):
        """Get a packet from the subnet."""
        return self.queue.get()


class Sender:
    """Uploads packets to the server using ABP."""
    
    def __init__(self, env: simpy.Environment, subnet_out: Subnet, 
                 subnet_in: Subnet, logger: EventLogger):
        self.env = env
        self.subnet_out = subnet_out
        self.subnet_in = subnet_in
        self.logger = logger
        
        # State
        self.total_packets_to_send = 0
        self.packets_remaining = 0
        self.current_seq = 1
        self.current_bit = 0
        self.is_idle = True
        self.is_preparing = False
        self.waiting_for_ack = False
        self.ack_timeout_event = None
        
        # Control input queue
        self.control_queue = simpy.Store(env)
        
        # Start processes
        self.env.process(self._control_handler())
        self.env.process(self._main_loop())
        self.env.process(self._ack_receiver())
    
    def add_control(self, n: int):
        """Add packets to send."""
        self.control_queue.put(n)
    
    def _control_handler(self):
        """Handle control commands."""
        while True:
            n = yield self.control_queue.get()
            old_total = self.total_packets_to_send
            self.total_packets_to_send += n
            self.packets_remaining += n
            
            self.logger.log(
                timestamp_ms=self.env.now * 1000,
                model="sender",
                type="control_cmd",
                val={"added": n, "total_remaining": self.packets_remaining}
            )
            
            if self.is_idle and self.packets_remaining > 0:
                self.is_idle = False
    
    def _main_loop(self):
        """Main sender loop."""
        while True:
            if self.packets_remaining > 0 and not self.is_preparing and not self.waiting_for_ack:
                # Start preparation
                self.is_preparing = True
                self.logger.log(
                    timestamp_ms=self.env.now * 1000,
                    model="sender",
                    type="preparation_started",
                    val={"duration": 10000}
                )
                yield self.env.timeout(10)  # 10s preparation
                self.is_preparing = False
                
                # Send packet
                self._send_packet()
            
            yield self.env.timeout(0.1)
    
    def _send_packet(self, is_retry: bool = False):
        """Send a packet using ABP."""
        packet = Packet(self.current_seq, self.current_bit)
        self.subnet_out.put(packet, "sender", "server_receiver")
        
        self.logger.log(
            timestamp_ms=self.env.now * 1000,
            model="sender",
            type="packet_sent",
            val={"seq": self.current_seq, "bit": self.current_bit, "is_retry": is_retry}
        )
        
        self.waiting_for_ack = True
        
        # Set timeout for ACK (20s)
        if self.ack_timeout_event:
            self.ack_timeout_event.cancel()
        self.ack_timeout_event = self.env.process(self._ack_timeout())
    
    def _ack_timeout(self):
        """Handle ACK timeout."""
        try:
            yield self.env.timeout(20)  # 20s timeout
            if self.waiting_for_ack:
                self.logger.log(
                    timestamp_ms=self.env.now * 1000,
                    model="sender",
                    type="timeout",
                    val={"seq": self.current_seq}
                )
                # Retransmit
                self._send_packet(is_retry=True)
        except simpy.Interrupt:
            pass
    
    def _ack_receiver(self):
        """Receive ACKs from server."""
        while True:
            packet, source, dest = yield self.subnet_in.get()
            if dest == "sender" and source == "server_receiver":
                # This is an ACK
                if packet.bit == self.current_bit:
                    # Correct ACK received
                    if self.ack_timeout_event:
                        self.ack_timeout_event.interrupt()
                        self.ack_timeout_event = None
                    
                    self.logger.log(
                        timestamp_ms=self.env.now * 1000,
                        model="sender",
                        type="ack_received",
                        val={"bit": packet.bit}
                    )
                    
                    # Update state
                    self.current_seq += 1
                    self.current_bit = 1 - self.current_bit
                    self.packets_remaining -= 1
                    self.waiting_for_ack = False
                    
                    if self.packets_remaining == 0:
                        self.is_idle = True


class ServerReceiver:
    """Receives packets from Sender, processes them, sends ACKs."""
    
    def __init__(self, env: simpy.Environment, subnet_in: Subnet,
                 subnet_out: Subnet, storage_queue: deque, logger: EventLogger):
        self.env = env
        self.subnet_in = subnet_in
        self.subnet_out = subnet_out
        self.storage_queue = storage_queue
        self.logger = logger
        
        self.expected_bit = 0
        
        self.env.process(self._receive_loop())
    
    def _receive_loop(self):
        """Receive and process packets."""
        while True:
            packet, source, dest = yield self.subnet_in.get()
            if dest == "server_receiver" and source == "sender":
                # Log packet received
                self.logger.log(
                    timestamp_ms=self.env.now * 1000,
                    model="server_receiver",
                    type="packet_received",
                    val={"seq": packet.seq, "bit": packet.bit}
                )
                
                # Process with 3s delay
                yield self.env.timeout(3)
                
                if packet.bit == self.expected_bit:
                    # New packet
                    self.storage_queue.append(packet)
                    ack_bit = packet.bit
                    self.expected_bit = 1 - self.expected_bit
                else:
                    # Duplicate packet, resend previous ACK
                    ack_bit = 1 - self.expected_bit
                
                # Send ACK
                ack_packet = Packet(0, ack_bit)  # seq doesn't matter for ACK
                self.subnet_out.put(ack_packet, "server_receiver", "sender")
                
                self.logger.log(
                    timestamp_ms=self.env.now * 1000,
                    model="server_receiver",
                    type="ack_sent_to_sender",
                    val={"bit": ack_bit}
                )


class ServerSender:
    """Sends packets from storage queue to Receiver using ABP."""
    
    def __init__(self, env: simpy.Environment, subnet_out: Subnet,
                 subnet_in: Subnet, storage_queue: deque, logger: EventLogger):
        self.env = env
        self.subnet_out = subnet_out
        self.subnet_in = subnet_in
        self.storage_queue = storage_queue
        self.logger = logger
        
        self.download_allowed = False
        self.current_bit = 0
        self.waiting_for_ack = False
        self.current_packet = None
        self.ack_timeout_event = None
        
        self.request_queue = simpy.Store(env)
        
        self.env.process(self._request_handler())
        self.env.process(self._main_loop())
        self.env.process(self._ack_receiver())
    
    def set_request(self, allowed: bool):
        """Set download permission."""
        self.request_queue.put(allowed)
    
    def _request_handler(self):
        """Handle request commands."""
        while True:
            allowed = yield self.request_queue.get()
            self.download_allowed = allowed
            
            self.logger.log(
                timestamp_ms=self.env.now * 1000,
                model="server_sender",
                type="download_valve_change",
                val={"allowed": allowed}
            )
    
    def _main_loop(self):
        """Main server sender loop."""
        while True:
            if (self.download_allowed and 
                len(self.storage_queue) > 0 and 
                not self.waiting_for_ack):
                # Send packet
                self.current_packet = self.storage_queue.popleft()
                packet = Packet(self.current_packet.seq, self.current_bit)
                self.subnet_out.put(packet, "server_sender", "receiver")
                
                self.logger.log(
                    timestamp_ms=self.env.now * 1000,
                    model="server_sender",
                    type="packet_forwarded",
                    val={"seq": packet.seq, "bit": self.current_bit}
                )
                
                self.waiting_for_ack = True
                
                # Set timeout for ACK (20s)
                if self.ack_timeout_event:
                    self.ack_timeout_event.cancel()
                self.ack_timeout_event = self.env.process(self._ack_timeout())
            
            yield self.env.timeout(0.1)
    
    def _ack_timeout(self):
        """Handle ACK timeout."""
        try:
            yield self.env.timeout(20)  # 20s timeout
            if self.waiting_for_ack:
                # Retransmit
                packet = Packet(self.current_packet.seq, self.current_bit)
                self.subnet_out.put(packet, "server_sender", "receiver")
                
                self.logger.log(
                    timestamp_ms=self.env.now * 1000,
                    model="server_sender",
                    type="packet_forwarded",
                    val={"seq": packet.seq, "bit": self.current_bit}
                )
                
                # Reset timeout
                self.ack_timeout_event = self.env.process(self._ack_timeout())
        except simpy.Interrupt:
            pass
    
    def _ack_receiver(self):
        """Receive ACKs from receiver."""
        while True:
            packet, source, dest = yield self.subnet_in.get()
            if dest == "server_sender" and source == "receiver":
                # This is an ACK
                if packet.bit == self.current_bit:
                    # Correct ACK received
                    if self.ack_timeout_event:
                        self.ack_timeout_event.interrupt()
                        self.ack_timeout_event = None
                    
                    self.logger.log(
                        timestamp_ms=self.env.now * 1000,
                        model="server_sender",
                        type="ack_received_from_receiver",
                        val={"bit": packet.bit}
                    )
                    
                    # Update state
                    self.current_bit = 1 - self.current_bit
                    self.waiting_for_ack = False
                    self.current_packet = None


class Receiver:
    """Receives packets from Server, processes them, sends ACKs."""
    
    def __init__(self, env: simpy.Environment, subnet_in: Subnet,
                 subnet_out: Subnet, logger: EventLogger):
        self.env = env
        self.subnet_in = subnet_in
        self.subnet_out = subnet_out
        self.logger = logger
        
        self.expected_bit = 0
        
        self.env.process(self._receive_loop())
    
    def _receive_loop(self):
        """Receive and process packets."""
        while True:
            packet, source, dest = yield self.subnet_in.get()
            if dest == "receiver" and source == "server_sender":
                # Log processing started
                self.logger.log(
                    timestamp_ms=self.env.now * 1000,
                    model="receiver",
                    type="processing_started",
                    val={"seq": packet.seq, "duration": 10000}
                )
                
                # Process with 10s delay
                yield self.env.timeout(10)
                
                if packet.bit == self.expected_bit:
                    # New packet
                    ack_bit = packet.bit
                    self.expected_bit = 1 - self.expected_bit
                else:
                    # Duplicate packet, resend previous ACK
                    ack_bit = 1 - self.expected_bit
                
                # Send ACK
                ack_packet = Packet(0, ack_bit)
                self.subnet_out.put(ack_packet, "receiver", "server_sender")
                
                self.logger.log(
                    timestamp_ms=self.env.now * 1000,
                    model="receiver",
                    type="ack_sent",
                    val={"bit": ack_bit}
                )


def parse_time(time_str: str) -> float:
    """Parse time string to seconds."""
    # Format: HH:MM:SS or HH:MM:SS:mmm
    parts = time_str.split(':')
    if len(parts) == 3:
        # HH:MM:SS
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
        return hours * 3600 + minutes * 60 + seconds
    elif len(parts) == 4:
        # HH:MM:SS:mmm
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
        millis = int(parts[3])
        return hours * 3600 + minutes * 60 + seconds + millis / 1000
    else:
        raise ValueError(f"Invalid time format: {time_str}")


def parse_input_commands(env: simpy.Environment, sender: Sender, 
                         server_sender: ServerSender):
    """Parse input commands from stdin and schedule them."""
    commands = []
    
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        
        parts = line.split()
        if len(parts) != 3:
            logger.warning(f"Invalid input line: {line}")
            continue
        
        time_str, cmd_type, value = parts
        time = parse_time(time_str)
        
        if cmd_type == "control":
            n = int(value)
            commands.append((time, "control", n))
        elif cmd_type == "request":
            allowed = value == "1"
            commands.append((time, "request", allowed))
        else:
            logger.warning(f"Unknown command type: {cmd_type}")
    
    # Sort commands by time
    commands.sort(key=lambda x: x[0])
    
    # Schedule commands
    for time, cmd_type, value in commands:
        if cmd_type == "control":
            env.process(_schedule_control(env, sender, time, value))
        elif cmd_type == "request":
            env.process(_schedule_request(env, server_sender, time, value))


def _schedule_control(env: simpy.Environment, sender: Sender, time: float, n: int):
    """Schedule a control command."""
    yield env.timeout(time)
    sender.add_control(n)


def _schedule_request(env: simpy.Environment, server_sender: ServerSender, 
                      time: float, allowed: bool):
    """Schedule a request command."""
    yield env.timeout(time)
    server_sender.set_request(allowed)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Dropbox-like synchronization simulation using ABP"
    )
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=10000000.0,
        help="Simulation duration in milliseconds (simulation time)"
    )
    args = parser.parse_args()
    
    # Convert to seconds for simpy
    simulation_time = args.simulation_time / 1000.0
    
    logger.info(f"Starting simulation for {simulation_time} seconds")
    
    # Create environment
    env = simpy.Environment()
    
    # Create event logger
    event_logger = EventLogger()
    
    # Create storage queue (shared between ServerReceiver and ServerSender)
    storage_queue = deque()
    
    # Create subnets (3s delay each)
    subnet_a1 = Subnet(env, "A1", 3, event_logger)  # Sender -> Server
    subnet_a2 = Subnet(env, "A2", 3, event_logger)  # Server -> Sender
    subnet_b1 = Subnet(env, "B1", 3, event_logger)  # Server -> Receiver
    subnet_b2 = Subnet(env, "B2", 3, event_logger)  # Receiver -> Server
    
    # Create components
    sender = Sender(env, subnet_a1, subnet_a2, event_logger)
    server_receiver = ServerReceiver(env, subnet_a1, subnet_a2, storage_queue, event_logger)
    server_sender = ServerSender(env, subnet_b1, subnet_b2, storage_queue, event_logger)
    receiver = Receiver(env, subnet_b1, subnet_b2, event_logger)
    
    # Parse and schedule input commands
    parse_input_commands(env, sender, server_sender)
    
    # Run simulation
    env.run(until=simulation_time)
    
    logger.info("Simulation completed")


if __name__ == "__main__":
    main()
