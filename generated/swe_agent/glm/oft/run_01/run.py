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


class Subnet:
    """Reliable, FIFO, fixed delay channel."""
    def __init__(self, env, name, delay_ms, output_callback):
        self.env = env
        self.name = name
        self.delay_ms = delay_ms
        self.output_callback = output_callback
        self.queue = deque()
        self.process = env.process(self.run())
    
    def send(self, packet, source, dest):
        """Send a packet through the subnet."""
        self.queue.append((packet, source, dest))
    
    def run(self):
        """Process packets with fixed delay."""
        while True:
            if self.queue:
                packet, source, dest = self.queue.popleft()
                yield self.env.timeout(self.delay_ms)
                # Schedule the callback as a process
                self.env.process(self.output_callback(packet, source, dest))
            else:
                yield self.env.timeout(1)  # Small idle wait


class Sender:
    """Uploads packets to the server using ABP protocol."""
    def __init__(self, env, subnet_a1, output_callback):
        self.env = env
        self.subnet_a1 = subnet_a1
        self.output_callback = output_callback
        
        # State
        self.total_packets_to_send = 0
        self.packets_remaining = 0
        self.current_seq = 1
        self.current_bit = 0
        self.is_idle = True
        self.is_preparing = False
        self.waiting_for_ack = False
        self.last_packet_sent = None
        self.timeout_event = None
        self.ack_timeout_ms = 20000
        self.preparation_time_ms = 10000
        
        # Process
        self.process = env.process(self.run())
    
    def handle_control(self, n):
        """Handle control command - add packets to upload queue."""
        self.total_packets_to_send += n
        self.packets_remaining += n
        
        self.output_callback({
            "timestamp_ms": self.env.now,
            "model": "sender",
            "type": "control_cmd",
            "val": {"added": n, "total_remaining": self.packets_remaining}
        })
        
        if self.is_idle and self.packets_remaining > 0:
            self.is_idle = False
    
    def handle_ack(self, bit):
        """Handle ACK from server."""
        if not self.waiting_for_ack:
            return
        
        if bit == self.current_bit:
            # Correct ACK
            self.output_callback({
                "timestamp_ms": self.env.now,
                "model": "sender",
                "type": "ack_received",
                "val": {"bit": bit}
            })
            
            # Cancel timeout by interrupting
            if self.timeout_event is not None:
                self.timeout_event.interrupt()
                self.timeout_event = None
            
            self.waiting_for_ack = False
            self.current_bit = 1 - self.current_bit  # Flip bit
            self.current_seq += 1
            self.packets_remaining -= 1
            
            if self.packets_remaining == 0:
                self.is_idle = True
        else:
            # Wrong ACK - ignore, will timeout
            pass
    
    def run(self):
        """Main sender loop."""
        while True:
            if self.is_idle:
                yield self.env.timeout(10)  # Idle wait
            elif self.packets_remaining > 0 and not self.waiting_for_ack:
                # Start preparation
                self.is_preparing = True
                self.output_callback({
                    "timestamp_ms": self.env.now,
                    "model": "sender",
                    "type": "preparation_started",
                    "val": {"duration": self.preparation_time_ms}
                })
                yield self.env.timeout(self.preparation_time_ms)
                self.is_preparing = False
                
                # Send packet
                packet = Packet(self.current_seq, self.current_bit)
                self.last_packet_sent = packet
                self.waiting_for_ack = True
                
                is_retry = False
                self.output_callback({
                    "timestamp_ms": self.env.now,
                    "model": "sender",
                    "type": "packet_sent",
                    "val": {"seq": packet.seq, "bit": packet.bit, "is_retry": is_retry}
                })
                
                self.subnet_a1.send(packet, "sender", "server_receiver")
                
                # Start timeout timer
                self.timeout_event = self.env.process(self.timeout_process(packet.seq))
            elif self.waiting_for_ack:
                # Waiting for ACK
                yield self.env.timeout(10)
            else:
                yield self.env.timeout(10)
    
    def timeout_process(self, seq):
        """Handle timeout for ACK."""
        try:
            yield self.env.timeout(self.ack_timeout_ms)
            if self.waiting_for_ack and self.last_packet_sent and self.last_packet_sent.seq == seq:
                # Timeout occurred
                self.output_callback({
                    "timestamp_ms": self.env.now,
                    "model": "sender",
                    "type": "timeout",
                    "val": {"seq": seq}
                })
                
                # Retransmit
                packet = self.last_packet_sent
                self.output_callback({
                    "timestamp_ms": self.env.now,
                    "model": "sender",
                    "type": "packet_sent",
                    "val": {"seq": packet.seq, "bit": packet.bit, "is_retry": True}
                })
                
                self.subnet_a1.send(packet, "sender", "server_receiver")
                
                # Restart timeout
                self.timeout_event = self.env.process(self.timeout_process(seq))
        except simpy.Interrupt:
            pass


class ServerReceiver:
    """Receives data from sender, processes and stores."""
    def __init__(self, env, subnet_a2, storage_queue, output_callback):
        self.env = env
        self.subnet_a2 = subnet_a2
        self.storage_queue = storage_queue
        self.output_callback = output_callback
        
        # ABP state
        self.expected_bit = 0
        
        # Process
        self.process = env.process(self.run())
    
    def handle_packet(self, packet):
        """Handle incoming packet from sender."""
        self.output_callback({
            "timestamp_ms": self.env.now,
            "model": "server_receiver",
            "type": "packet_received",
            "val": {"seq": packet.seq, "bit": packet.bit}
        })
        
        # Process with 3s delay
        yield self.env.timeout(3000)
        
        if packet.bit == self.expected_bit:
            # New packet
            self.storage_queue.append(packet)
            ack_bit = packet.bit
            self.expected_bit = 1 - self.expected_bit
        else:
            # Duplicate packet
            ack_bit = 1 - self.expected_bit  # Send ACK for previous bit
        
        # Send ACK
        self.output_callback({
            "timestamp_ms": self.env.now,
            "model": "server_receiver",
            "type": "ack_sent_to_sender",
            "val": {"bit": ack_bit}
        })
        
        self.subnet_a2.send(ack_bit, "server_receiver", "sender")
    
    def run(self):
        """Main loop - mostly idle, packets handled via handle_packet."""
        while True:
            yield self.env.timeout(100)


class ServerSender:
    """Sends data from storage queue to receiver using ABP."""
    def __init__(self, env, subnet_b1, storage_queue, output_callback):
        self.env = env
        self.subnet_b1 = subnet_b1
        self.storage_queue = storage_queue
        self.output_callback = output_callback
        
        # State
        self.download_allowed = False
        self.waiting_for_ack = False
        self.current_packet = None
        self.ack_timeout_ms = 20000
        self.timeout_event = None
        
        # Process
        self.process = env.process(self.run())
    
    def handle_request(self, allowed):
        """Handle request command - toggle download permission."""
        self.download_allowed = allowed
        self.output_callback({
            "timestamp_ms": self.env.now,
            "model": "server_sender",
            "type": "download_valve_change",
            "val": {"allowed": allowed}
        })
    
    def handle_ack(self, bit):
        """Handle ACK from receiver."""
        if not self.waiting_for_ack:
            return
        
        if self.current_packet and bit == self.current_packet.bit:
            # Correct ACK
            self.output_callback({
                "timestamp_ms": self.env.now,
                "model": "server_sender",
                "type": "ack_received_from_receiver",
                "val": {"bit": bit}
            })
            
            # Cancel timeout by interrupting
            if self.timeout_event is not None:
                self.timeout_event.interrupt()
                self.timeout_event = None
            
            self.waiting_for_ack = False
            self.current_packet = None
        else:
            # Wrong ACK - ignore, will timeout
            pass
    
    def run(self):
        """Main server sender loop."""
        while True:
            if (self.download_allowed and 
                self.storage_queue and 
                not self.waiting_for_ack):
                # Send packet
                packet = self.storage_queue.popleft()
                self.current_packet = packet
                self.waiting_for_ack = True
                
                self.output_callback({
                    "timestamp_ms": self.env.now,
                    "model": "server_sender",
                    "type": "packet_forwarded",
                    "val": {"seq": packet.seq, "bit": packet.bit}
                })
                
                self.subnet_b1.send(packet, "server_sender", "receiver")
                
                # Start timeout timer
                self.timeout_event = self.env.process(self.timeout_process(packet.seq))
            else:
                yield self.env.timeout(10)
    
    def timeout_process(self, seq):
        """Handle timeout for ACK."""
        try:
            yield self.env.timeout(self.ack_timeout_ms)
            if (self.waiting_for_ack and 
                self.current_packet and 
                self.current_packet.seq == seq):
                # Timeout occurred - retransmit
                packet = self.current_packet
                self.output_callback({
                    "timestamp_ms": self.env.now,
                    "model": "server_sender",
                    "type": "packet_forwarded",
                    "val": {"seq": packet.seq, "bit": packet.bit}
                })
                
                self.subnet_b1.send(packet, "server_sender", "receiver")
                
                # Restart timeout
                self.timeout_event = self.env.process(self.timeout_process(seq))
        except simpy.Interrupt:
            pass


class Receiver:
    """Receives data from server, processes and sends ACK."""
    def __init__(self, env, subnet_b2, output_callback):
        self.env = env
        self.subnet_b2 = subnet_b2
        self.output_callback = output_callback
        
        # Process
        self.process = env.process(self.run())
    
    def handle_packet(self, packet):
        """Handle incoming packet from server."""
        # Start processing with 10s delay
        self.output_callback({
            "timestamp_ms": self.env.now,
            "model": "receiver",
            "type": "processing_started",
            "val": {"seq": packet.seq, "duration": 10000}
        })
        
        yield self.env.timeout(10000)
        
        # Send ACK
        self.output_callback({
            "timestamp_ms": self.env.now,
            "model": "receiver",
            "type": "ack_sent",
            "val": {"bit": packet.bit}
        })
        
        self.subnet_b2.send(packet.bit, "receiver", "server_sender")
    
    def run(self):
        """Main loop - mostly idle, packets handled via handle_packet."""
        while True:
            yield self.env.timeout(100)


def parse_time(time_str):
    """Parse time string HH:MM:SS or HH:MM:SS:mmm to milliseconds."""
    parts = time_str.split(':')
    if len(parts) == 3:
        # HH:MM:SS
        hours, minutes, seconds = map(int, parts)
        return (hours * 3600 + minutes * 60 + seconds) * 1000
    elif len(parts) == 4:
        # HH:MM:SS:mmm
        hours, minutes, seconds, millis = map(int, parts)
        return (hours * 3600 + minutes * 60 + seconds) * 1000 + millis
    else:
        raise ValueError(f"Invalid time format: {time_str}")


def read_stdin_commands():
    """Read commands from stdin."""
    commands = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 3:
            logger.warning(f"Invalid line format: {line}")
            continue
        time_str, cmd_type, value = parts
        time_ms = parse_time(time_str)
        if cmd_type == "control":
            commands.append((time_ms, "control", int(value)))
        elif cmd_type == "request":
            commands.append((time_ms, "request", int(value)))
        else:
            logger.warning(f"Unknown command type: {cmd_type}")
    return commands


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Dropbox-like synchronization simulation"
    )
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=10000000.0,
        help="Simulation duration in milliseconds"
    )
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Storage queue (shared between server_receiver and server_sender)
    storage_queue = deque()
    
    # Output events list
    events = []
    
    def output_callback(event):
        """Callback to record events."""
        events.append(event)
    
    # Create subnets (3s delay = 3000ms)
    # A1: Sender -> Server
    # A2: Server -> Sender
    # B1: Server -> Receiver
    # B2: Receiver -> Server
    def subnet_a1_callback(packet, source, dest):
        """Callback for subnet A1 (Sender -> Server)."""
        yield env.process(server_receiver.handle_packet(packet))
    
    def subnet_a2_callback(bit, source, dest):
        """Callback for subnet A2 (Server -> Sender)."""
        sender.handle_ack(bit)
        yield env.timeout(0)
    
    def subnet_b1_callback(packet, source, dest):
        """Callback for subnet B1 (Server -> Receiver)."""
        yield env.process(receiver.handle_packet(packet))
    
    def subnet_b2_callback(bit, source, dest):
        """Callback for subnet B2 (Receiver -> Server)."""
        server_sender.handle_ack(bit)
        yield env.timeout(0)
    
    subnet_a1 = Subnet(env, "A1", 3000, subnet_a1_callback)
    subnet_a2 = Subnet(env, "A2", 3000, subnet_a2_callback)
    subnet_b1 = Subnet(env, "B1", 3000, subnet_b1_callback)
    subnet_b2 = Subnet(env, "B2", 3000, subnet_b2_callback)
    
    # Create entities
    sender = Sender(env, subnet_a1, output_callback)
    server_receiver = ServerReceiver(env, subnet_a2, storage_queue, output_callback)
    server_sender = ServerSender(env, subnet_b1, storage_queue, output_callback)
    receiver = Receiver(env, subnet_b2, output_callback)
    
    # Read stdin commands
    commands = read_stdin_commands()
    
    # Schedule commands
    def schedule_control(time_ms, value):
        """Schedule a control command."""
        yield env.timeout(time_ms)
        sender.handle_control(value)
    
    def schedule_request(time_ms, value):
        """Schedule a request command."""
        yield env.timeout(time_ms)
        server_sender.handle_request(bool(value))
    
    for time_ms, cmd_type, value in commands:
        if cmd_type == "control":
            env.process(schedule_control(time_ms, value))
        elif cmd_type == "request":
            env.process(schedule_request(time_ms, value))
    
    # Run simulation
    logger.info(f"Starting simulation for {args.simulation_time}ms")
    env.run(until=args.simulation_time)
    logger.info("Simulation completed")
    
    # Sort events by timestamp and output as JSONL
    events.sort(key=lambda e: e["timestamp_ms"])
    for event in events:
        print(json.dumps(event))


if __name__ == "__main__":
    main()