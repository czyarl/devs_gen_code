#!/usr/bin/env python3
"""
Dropbox-like synchronization simulation using two ABP loops.
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
    """Represents a data packet with sequence number and alternating bit."""
    
    def __init__(self, seq: int, bit: int):
        self.seq = seq
        self.bit = bit
    
    def __repr__(self):
        return f"Packet(seq={self.seq}, bit={self.bit})"


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
        self.events.append(event)
        print(json.dumps(event))
        sys.stdout.flush()
    
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
        self.event_logger = logger
        self.store = simpy.Store(env)
    
    def put(self, item):
        """Put an item into the subnet."""
        self.env.process(self._transmit(item))
    
    def _transmit(self, item):
        """Transmit item with delay."""
        yield self.env.timeout(self.delay)
        yield self.store.put(item)
    
    def get(self):
        """Get an item from the subnet."""
        return self.store.get()


class Sender:
    """Uploads packets to server using ABP protocol."""
    
    def __init__(self, env: simpy.Environment, subnet_out: Subnet, subnet_in: Subnet, logger: EventLogger):
        self.env = env
        self.subnet_out = subnet_out
        self.subnet_in = subnet_in
        self.event_logger = logger
        
        self.total_packets_to_send = 0
        self.packets_remaining = 0
        self.current_seq = 1
        self.current_bit = 0
        self.waiting_for_ack = False
        self.last_sent_packet = None
        self.timeout_event = None
        self.preparation_done = None
        
        # Control for starting/stopping
        self.control_store = simpy.Store(env)
        
        # Start the main process
        self.env.process(self.run())
        self.env.process(self.receive_ack())
    
    def add_packets(self, count: int):
        """Add packets to send queue."""
        self.total_packets_to_send += count
        self.packets_remaining += count
        timestamp_ms = self.env.now * 1000
        self.event_logger.log_control_cmd(timestamp_ms, count, self.packets_remaining)
        # Wake up if idle
        if not self.waiting_for_ack and self.packets_remaining > 0:
            if self.preparation_done is not None and not self.preparation_done.triggered:
                pass  # Already preparing
            else:
                # Trigger preparation if not already started
                pass
    
    def run(self):
        """Main sender process."""
        while True:
            # Wait for packets to send
            if self.packets_remaining == 0:
                yield self.env.timeout(1)  # Small idle check
                continue
            
            # Start preparation
            timestamp_ms = self.env.now * 1000
            self.event_logger.log_preparation_started(timestamp_ms, 10000)
            yield self.env.timeout(10)  # 10s preparation
            
            # Send packet
            self.send_packet()
            
            # Wait for ACK or timeout
            self.timeout_event = self.env.event()
            self.waiting_for_ack = True
            
            # Wait for ACK (20s timeout)
            try:
                yield self.timeout_event | self.env.timeout(20)
            except:
                pass
            
            if not self.timeout_event.triggered:
                # Timeout occurred
                timestamp_ms = self.env.now * 1000
                self.event_logger.log_timeout(timestamp_ms, self.current_seq)
                # Retransmit
                self.send_packet(is_retry=True)
                # Wait again for ACK
                self.timeout_event = self.env.event()
                try:
                    yield self.timeout_event | self.env.timeout(20)
                except:
                    pass
            
            self.waiting_for_ack = False
    
    def send_packet(self, is_retry: bool = False):
        """Send a packet to the server."""
        packet = Packet(self.current_seq, self.current_bit)
        self.last_sent_packet = packet
        timestamp_ms = self.env.now * 1000
        self.event_logger.log_packet_sent(timestamp_ms, packet.seq, packet.bit, is_retry)
        self.subnet_out.put(packet)
    
    def receive_ack(self):
        """Process incoming ACKs."""
        while True:
            ack_bit = yield self.subnet_in.get()
            timestamp_ms = self.env.now * 1000
            self.event_logger.log_ack_received(timestamp_ms, ack_bit)
            
            if self.waiting_for_ack and ack_bit == self.current_bit:
                # Correct ACK received
                self.timeout_event.succeed()
                # Flip bit and increment seq
                self.current_bit = 1 - self.current_bit
                self.current_seq += 1
                self.packets_remaining -= 1


class ServerReceiver:
    """Receives packets from sender, processes them, and stores in queue."""
    
    def __init__(self, env: simpy.Environment, subnet_in: Subnet, subnet_out: Subnet, 
                 storage_queue: deque, logger: EventLogger):
        self.env = env
        self.subnet_in = subnet_in
        self.subnet_out = subnet_out
        self.storage_queue = storage_queue
        self.event_logger = logger
        
        self.expected_bit = 0
        
        self.env.process(self.run())
    
    def run(self):
        """Main server receiver process."""
        while True:
            packet = yield self.subnet_in.get()
            timestamp_ms = self.env.now * 1000
            self.event_logger.log_packet_received(timestamp_ms, packet.seq, packet.bit)
            
            # 3s processing delay
            yield self.env.timeout(3)
            
            if packet.bit == self.expected_bit:
                # New packet
                self.storage_queue.append(packet)
                self.event_logger.log_ack_sent_to_sender(self.env.now * 1000, packet.bit)
                self.subnet_out.put(packet.bit)
                self.expected_bit = 1 - self.expected_bit
            else:
                # Duplicate packet, resend previous ACK
                prev_bit = 1 - packet.bit
                self.event_logger.log_ack_sent_to_sender(self.env.now * 1000, prev_bit)
                self.subnet_out.put(prev_bit)


class ServerSender:
    """Sends packets from storage queue to receiver using ABP."""
    
    def __init__(self, env: simpy.Environment, subnet_out: Subnet, subnet_in: Subnet,
                 storage_queue: deque, logger: EventLogger):
        self.env = env
        self.subnet_out = subnet_out
        self.subnet_in = subnet_in
        self.storage_queue = storage_queue
        self.event_logger = logger
        
        self.download_allowed = False
        self.waiting_for_ack = False
        self.current_packet = None
        self.timeout_event = None
        
        self.env.process(self.run())
        self.env.process(self.receive_ack())
    
    def set_download_allowed(self, allowed: bool):
        """Set download permission."""
        self.download_allowed = allowed
        timestamp_ms = self.env.now * 1000
        self.event_logger.log_download_valve_change(timestamp_ms, allowed)
    
    def run(self):
        """Main server sender process."""
        while True:
            # Check if we can send
            if not self.download_allowed or len(self.storage_queue) == 0 or self.waiting_for_ack:
                yield self.env.timeout(1)  # Small idle check
                continue
            
            # Get packet from queue
            packet = self.storage_queue[0]  # Peek
            self.current_packet = packet
            
            # Send packet (no processing delay)
            timestamp_ms = self.env.now * 1000
            self.event_logger.log_packet_forwarded(timestamp_ms, packet.seq, packet.bit)
            self.subnet_out.put(packet)
            
            # Wait for ACK (20s timeout)
            self.waiting_for_ack = True
            self.timeout_event = self.env.event()
            
            try:
                yield self.timeout_event | self.env.timeout(20)
            except:
                pass
            
            if not self.timeout_event.triggered:
                # Timeout occurred - retransmit
                timestamp_ms = self.env.now * 1000
                self.event_logger.log_packet_forwarded(timestamp_ms, packet.seq, packet.bit)
                self.subnet_out.put(packet)
                # Wait again
                self.timeout_event = self.env.event()
                try:
                    yield self.timeout_event | self.env.timeout(20)
                except:
                    pass
            
            self.waiting_for_ack = False
    
    def receive_ack(self):
        """Process incoming ACKs."""
        while True:
            ack_bit = yield self.subnet_in.get()
            timestamp_ms = self.env.now * 1000
            self.event_logger.log_ack_received_from_receiver(timestamp_ms, ack_bit)
            
            if self.waiting_for_ack and self.current_packet and ack_bit == self.current_packet.bit:
                # Correct ACK received
                self.timeout_event.succeed()
                # Remove packet from queue
                if self.storage_queue and self.storage_queue[0] == self.current_packet:
                    self.storage_queue.popleft()
                self.current_packet = None


class Receiver:
    """Receives packets from server, processes them, and sends ACKs."""
    
    def __init__(self, env: simpy.Environment, subnet_in: Subnet, subnet_out: Subnet, logger: EventLogger):
        self.env = env
        self.subnet_in = subnet_in
        self.subnet_out = subnet_out
        self.event_logger = logger
        
        self.env.process(self.run())
    
    def run(self):
        """Main receiver process."""
        while True:
            packet = yield self.subnet_in.get()
            
            # 10s processing delay
            timestamp_ms = self.env.now * 1000
            self.event_logger.log_processing_started(timestamp_ms, packet.seq, 10000)
            yield self.env.timeout(10)
            
            # Send ACK
            self.event_logger.log_ack_sent(self.env.now * 1000, packet.bit)
            self.subnet_out.put(packet.bit)


def parse_time(time_str: str) -> float:
    """Parse time string to seconds."""
    parts = time_str.split(':')
    if len(parts) == 3:
        # HH:MM:SS
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    elif len(parts) == 4:
        # HH:MM:SS:mmm
        hours, minutes, seconds, millis = parts
        return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + float(millis) / 1000
    else:
        raise ValueError(f"Invalid time format: {time_str}")


def parse_input_lines(lines):
    """Parse stdin lines into scheduled events."""
    events = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 3:
            logger.warning(f"Skipping invalid line: {line}")
            continue
        
        time_str, event_type, value = parts
        time = parse_time(time_str)
        
        if event_type == "control":
            events.append((time, "control", int(value)))
        elif event_type == "request":
            events.append((time, "request", int(value)))
        else:
            logger.warning(f"Unknown event type: {event_type}")
    
    events.sort(key=lambda x: x[0])
    return events


def schedule_input_events(env: simpy.Environment, events: list, sender: Sender, server_sender: ServerSender):
    """Schedule input events from stdin."""
    for time, event_type, value in events:
        env.process(lambda t=time, et=event_type, v=value: _input_event(env, t, et, v, sender, server_sender))


def _input_event(env: simpy.Environment, time: float, event_type: str, value: int, 
                 sender: Sender, server_sender: ServerSender):
    """Execute a scheduled input event."""
    yield env.timeout(time)
    if event_type == "control":
        sender.add_packets(value)
        logger.info(f"Time {time}s: control {value}")
    elif event_type == "request":
        server_sender.set_download_allowed(bool(value))
        logger.info(f"Time {time}s: request {value}")


def main():
    parser = argparse.ArgumentParser(description="Dropbox-like synchronization simulation")
    parser.add_argument("--simulation_time", type=float, default=10000000.0,
                        help="Simulation duration in milliseconds (default: 10000000.0)")
    args = parser.parse_args()
    
    # Convert to seconds for simpy
    sim_time_seconds = args.simulation_time / 1000.0
    
    # Read stdin
    lines = sys.stdin.readlines()
    input_events = parse_input_lines(lines)
    
    logger.info(f"Simulation time: {sim_time_seconds}s")
    logger.info(f"Input events: {len(input_events)}")
    
    # Create environment
    env = simpy.Environment()
    event_logger = EventLogger()
    
    # Create storage queue
    storage_queue = deque()
    
    # Create subnets (3s delay each)
    subnet_a1 = Subnet(env, "A1", 3, event_logger)  # Sender -> Server
    subnet_a2 = Subnet(env, "A2", 3, event_logger)  # Server -> Sender (ACK)
    subnet_b1 = Subnet(env, "B1", 3, event_logger)  # Server -> Receiver
    subnet_b2 = Subnet(env, "B2", 3, event_logger)  # Receiver -> Server (ACK)
    
    # Create entities
    sender = Sender(env, subnet_a1, subnet_a2, event_logger)
    server_receiver = ServerReceiver(env, subnet_a1, subnet_a2, storage_queue, event_logger)
    server_sender = ServerSender(env, subnet_b1, subnet_b2, storage_queue, event_logger)
    receiver = Receiver(env, subnet_b1, subnet_b2, event_logger)
    
    # Schedule input events
    schedule_input_events(env, input_events, sender, server_sender)
    
    # Run simulation
    logger.info("Starting simulation...")
    env.run(until=sim_time_seconds)
    logger.info("Simulation completed.")


if __name__ == "__main__":
    main()
