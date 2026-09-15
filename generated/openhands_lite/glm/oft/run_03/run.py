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
    
    def to_dict(self) -> Dict[str, Any]:
        return {"seq": self.seq, "bit": self.bit}


class Subnet:
    """Reliable FIFO channel with fixed delay."""
    def __init__(self, env: simpy.Environment, name: str, delay: float):
        self.env = env
        self.name = name
        self.delay = delay
        self.queue = simpy.Store(env)
    
    def put(self, item: Any):
        """Put item into subnet with delay."""
        def delayed_put():
            yield self.env.timeout(self.delay)
            yield self.queue.put(item)
        self.env.process(delayed_put())
    
    def get(self):
        """Get item from subnet."""
        return self.queue.get()


class Sender:
    """Uploads packets to server using ABP protocol."""
    def __init__(self, env: simpy.Environment, subnet_out: Subnet, subnet_in: Subnet):
        self.env = env
        self.subnet_out = subnet_out
        self.subnet_in = subnet_in
        self.total_packets_to_send = 0
        self.packets_remaining = 0
        self.current_seq = 1
        self.current_bit = 0
        self.is_busy = False
        self.waiting_for_ack = False
        self.ack_timeout_event = None
        self.control_events = []
    
    def add_control(self, count: int, timestamp_ms: float):
        """Add packets to upload queue."""
        self.total_packets_to_send += count
        self.packets_remaining += count
        self.control_events.append((timestamp_ms, count, self.packets_remaining))
        
        # Log control command
        self.log_event("control_cmd", {"added": count, "total_remaining": self.packets_remaining})
        
        # Wake up if idle
        if not self.is_busy and self.packets_remaining > 0:
            self.is_busy = True
            self.env.process(self.run())
    
    def log_event(self, event_type: str, val: Dict[str, Any]):
        """Log event to stdout."""
        event = {
            "timestamp_ms": self.env.now,
            "model": "sender",
            "type": event_type,
            "val": val
        }
        print(json.dumps(event))
    
    def run(self):
        """Main sender loop."""
        while self.packets_remaining > 0:
            # Preparation phase (10s)
            self.log_event("preparation_started", {"duration": 10000})
            yield self.env.timeout(10000)
            
            # Send packet
            is_retry = False
            while True:
                packet = Packet(self.current_seq, self.current_bit)
                self.log_event("packet_sent", {"seq": packet.seq, "bit": packet.bit, "is_retry": is_retry})
                self.subnet_out.put(packet)
                self.waiting_for_ack = True
                
                # Wait for ACK or timeout (20s)
                try:
                    ack_packet = yield self.env.process(self.wait_for_ack())
                    self.waiting_for_ack = False
                    
                    # Check if ACK bit matches
                    if ack_packet.bit == self.current_bit:
                        self.log_event("ack_received", {"bit": ack_packet.bit})
                        # Success: flip bit, increment seq, decrement remaining
                        self.current_bit = 1 - self.current_bit
                        self.current_seq += 1
                        self.packets_remaining -= 1
                        break
                    else:
                        # Wrong ACK bit, should not happen in ABP
                        logger.warning(f"Received wrong ACK bit: {ack_packet.bit}, expected {self.current_bit}")
                except simpy.Interrupt:
                    # Timeout occurred
                    self.log_event("timeout", {"seq": self.current_seq})
                    is_retry = True
                    # Retry same packet
        
        # All packets sent
        self.is_busy = False
    
    def wait_for_ack(self):
        """Wait for ACK with timeout."""
        def ack_receiver():
            ack = yield self.subnet_in.get()
            return ack
        
        ack_process = self.env.process(ack_receiver())
        timeout = self.env.timeout(20000)
        
        result = yield ack_process | timeout
        
        if ack_process in result:
            return ack_process.value
        else:
            ack_process.interrupt()
            raise simpy.Interrupt("Timeout")


class ServerReceiver:
    """Receives packets from sender, processes and stores them."""
    def __init__(self, env: simpy.Environment, subnet_in: Subnet, subnet_out: Subnet, storage_queue: deque):
        self.env = env
        self.subnet_in = subnet_in
        self.subnet_out = subnet_out
        self.storage_queue = storage_queue
        self.expected_bit = 0
    
    def log_event(self, event_type: str, val: Dict[str, Any]):
        """Log event to stdout."""
        event = {
            "timestamp_ms": self.env.now,
            "model": "server_receiver",
            "type": event_type,
            "val": val
        }
        print(json.dumps(event))
    
    def run(self):
        """Main server receiver loop."""
        while True:
            # Receive packet
            packet = yield self.subnet_in.get()
            self.log_event("packet_received", {"seq": packet.seq, "bit": packet.bit})
            
            # Processing delay (3s)
            yield self.env.timeout(3000)
            
            # Check bit and send ACK
            if packet.bit == self.expected_bit:
                # New packet
                self.storage_queue.append(packet)
                self.expected_bit = 1 - self.expected_bit
            else:
                # Duplicate packet, don't add to storage
                pass
            
            # Send ACK with the bit we received
            self.log_event("ack_sent_to_sender", {"bit": packet.bit})
            self.subnet_out.put(Packet(0, packet.bit))  # ACK packet


class ServerSender:
    """Sends packets from storage to receiver using ABP protocol."""
    def __init__(self, env: simpy.Environment, subnet_out: Subnet, subnet_in: Subnet, storage_queue: deque):
        self.env = env
        self.subnet_out = subnet_out
        self.subnet_in = subnet_in
        self.storage_queue = storage_queue
        self.download_allowed = False
        self.current_seq = 1
        self.current_bit = 0
        self.waiting_for_ack = False
        self.request_events = []
    
    def set_download_allowed(self, allowed: bool, timestamp_ms: float):
        """Set download permission."""
        self.download_allowed = allowed
        self.request_events.append((timestamp_ms, allowed))
        
        # Log download valve change
        self.log_event("download_valve_change", {"allowed": allowed})
        
        # Wake up if allowed and storage not empty
        if allowed and len(self.storage_queue) > 0 and not self.waiting_for_ack:
            self.env.process(self.run())
    
    def log_event(self, event_type: str, val: Dict[str, Any]):
        """Log event to stdout."""
        event = {
            "timestamp_ms": self.env.now,
            "model": "server_sender",
            "type": event_type,
            "val": val
        }
        print(json.dumps(event))
    
    def run(self):
        """Main server sender loop."""
        while self.download_allowed and len(self.storage_queue) > 0:
            # Get packet from storage
            packet = self.storage_queue.popleft()
            
            # Forward packet
            self.log_event("packet_forwarded", {"seq": packet.seq, "bit": packet.bit})
            self.subnet_out.put(packet)
            self.waiting_for_ack = True
            
            # Wait for ACK with timeout (20s)
            is_retry = False
            while True:
                try:
                    ack_packet = yield self.env.process(self.wait_for_ack())
                    self.waiting_for_ack = False
                    
                    # Check if ACK bit matches
                    if ack_packet.bit == self.current_bit:
                        self.log_event("ack_received_from_receiver", {"bit": ack_packet.bit})
                        # Success: flip bit, increment seq
                        self.current_bit = 1 - self.current_bit
                        self.current_seq += 1
                        break
                    else:
                        # Wrong ACK bit, should not happen in ABP
                        logger.warning(f"Received wrong ACK bit: {ack_packet.bit}, expected {self.current_bit}")
                except simpy.Interrupt:
                    # Timeout occurred - retry
                    is_retry = True
                    self.log_event("packet_forwarded", {"seq": packet.seq, "bit": packet.bit})
                    self.subnet_out.put(packet)
    
    def wait_for_ack(self):
        """Wait for ACK with timeout."""
        def ack_receiver():
            ack = yield self.subnet_in.get()
            return ack
        
        ack_process = self.env.process(ack_receiver())
        timeout = self.env.timeout(20000)
        
        result = yield ack_process | timeout
        
        if ack_process in result:
            return ack_process.value
        else:
            ack_process.interrupt()
            raise simpy.Interrupt("Timeout")


class Receiver:
    """Receives packets from server, processes and acknowledges."""
    def __init__(self, env: simpy.Environment, subnet_in: Subnet, subnet_out: Subnet):
        self.env = env
        self.subnet_in = subnet_in
        self.subnet_out = subnet_out
        self.expected_bit = 0
    
    def log_event(self, event_type: str, val: Dict[str, Any]):
        """Log event to stdout."""
        event = {
            "timestamp_ms": self.env.now,
            "model": "receiver",
            "type": event_type,
            "val": val
        }
        print(json.dumps(event))
    
    def run(self):
        """Main receiver loop."""
        while True:
            # Receive packet
            packet = yield self.subnet_in.get()
            
            # Processing delay (10s)
            self.log_event("processing_started", {"seq": packet.seq, "duration": 10000})
            yield self.env.timeout(10000)
            
            # Send ACK with the bit we received (ABP: echo back the bit)
            self.log_event("ack_sent", {"bit": packet.bit})
            self.subnet_out.put(Packet(0, packet.bit))  # ACK packet


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


def parse_input_commands(env: simpy.Environment, sender: Sender, server_sender: ServerSender):
    """Parse input commands from stdin and schedule them."""
    commands = []
    
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        
        parts = line.split()
        if len(parts) != 3:
            logger.warning(f"Invalid command format: {line}")
            continue
        
        time_str, cmd_type, value_str = parts
        timestamp_ms = parse_time(time_str)
        value = int(value_str)
        
        commands.append((timestamp_ms, cmd_type, value))
    
    # Sort commands by timestamp
    commands.sort(key=lambda x: x[0])
    
    # Schedule commands
    for timestamp_ms, cmd_type, value in commands:
        def schedule_command(ts=timestamp_ms, ct=cmd_type, v=value):
            yield env.timeout(ts - env.now)
            if ct == "control":
                sender.add_control(v, ts)
            elif ct == "request":
                server_sender.set_download_allowed(v == 1, ts)
        
        env.process(schedule_command())


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Dropbox-like synchronization simulation")
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=10000000.0,
        help="Simulation duration in milliseconds (default: 10000000.0)"
    )
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create subnets (3s delay each)
    subnet_a1 = Subnet(env, "A1", 3000)  # Sender -> Server
    subnet_a2 = Subnet(env, "A2", 3000)  # Server -> Sender
    subnet_b1 = Subnet(env, "B1", 3000)  # Server -> Receiver
    subnet_b2 = Subnet(env, "B2", 3000)  # Receiver -> Server
    
    # Create storage queue
    storage_queue = deque()
    
    # Create entities
    sender = Sender(env, subnet_a1, subnet_a2)
    server_receiver = ServerReceiver(env, subnet_a1, subnet_a2, storage_queue)
    server_sender = ServerSender(env, subnet_b1, subnet_b2, storage_queue)
    receiver = Receiver(env, subnet_b1, subnet_b2)
    
    # Start entity processes
    env.process(server_receiver.run())
    env.process(receiver.run())
    
    # Parse and schedule input commands
    env.process(parse_input_commands(env, sender, server_sender))
    
    # Run simulation
    logger.info(f"Starting simulation for {args.simulation_time} ms")
    env.run(until=args.simulation_time)
    logger.info("Simulation completed")


if __name__ == "__main__":
    main()
