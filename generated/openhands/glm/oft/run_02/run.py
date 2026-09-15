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


class Subnet:
    """Reliable FIFO channel with fixed delay."""
    def __init__(self, env, name, delay_ms):
        self.env = env
        self.name = name
        self.delay_ms = delay_ms
        self.store = simpy.Store(env)
    
    def put(self, packet, source, dest):
        """Put packet into subnet with delay."""
        def _deliver():
            yield self.env.timeout(self.delay_ms)
            self.store.put((packet, source, dest))
        self.env.process(_deliver())
    
    def get(self):
        """Get packet from subnet."""
        return self.store.get()


class Sender:
    """Uploads packets to server using ABP."""
    def __init__(self, env, subnet_out, subnet_in, event_queue):
        self.env = env
        self.subnet_out = subnet_out
        self.subnet_in = subnet_in
        self.event_queue = event_queue
        
        self.total_packets_to_send = 0
        self.packets_remaining = 0
        self.current_seq = 1
        self.current_bit = 0
        self.is_busy = False
        self.waiting_for_ack = False
        self.ack_event = None
        self.received_ack = None
        self.upload_process = None
    
    def handle_control(self, added):
        """Handle control command to add packets."""
        was_idle = not self.is_busy and self.packets_remaining == 0
        self.total_packets_to_send += added
        self.packets_remaining += added
        
        self.event_queue.append({
            "timestamp_ms": self.env.now,
            "model": "sender",
            "type": "control_cmd",
            "val": {"added": added, "total_remaining": self.packets_remaining}
        })
        
        if was_idle and self.packets_remaining > 0:
            self.is_busy = True
            self.upload_process = self.env.process(self.upload_loop())
    
    def upload_loop(self):
        """Main upload loop."""
        while self.packets_remaining > 0:
            # Preparation phase (10s)
            self.event_queue.append({
                "timestamp_ms": self.env.now,
                "model": "sender",
                "type": "preparation_started",
                "val": {"duration": 10000}
            })
            yield self.env.timeout(10000)
            
            # Send packet
            packet = Packet(self.current_seq, self.current_bit)
            is_retry = False
            self.subnet_out.put(packet, "sender", "server_receiver")
            
            self.event_queue.append({
                "timestamp_ms": self.env.now,
                "model": "sender",
                "type": "packet_sent",
                "val": {"seq": packet.seq, "bit": packet.bit, "is_retry": is_retry}
            })
            
            # Wait for ACK with timeout (20s)
            self.waiting_for_ack = True
            self.ack_event = self.env.event()
            self.received_ack = None
            
            # Start a process to wait for ACK from subnet
            def _wait_for_ack():
                ack_packet, source, dest = yield self.subnet_in.get()
                self.received_ack = ack_packet
                if self.ack_event and not self.ack_event.triggered:
                    self.ack_event.succeed()
            
            self.env.process(_wait_for_ack())
            
            # Wait for ACK with timeout
            timeout_event = self.env.timeout(20000)
            result = yield self.ack_event | timeout_event
            
            if self.ack_event in result:
                # ACK received
                ack_bit = self.received_ack.bit
                self.event_queue.append({
                    "timestamp_ms": self.env.now,
                    "model": "sender",
                    "type": "ack_received",
                    "val": {"bit": ack_bit}
                })
                
                if ack_bit == self.current_bit:
                    # Correct ACK, advance
                    self.current_bit = 1 - self.current_bit
                    self.current_seq += 1
                    self.packets_remaining -= 1
                # If wrong bit, it's a duplicate ACK, just retry
            else:
                # Timeout occurred
                self.event_queue.append({
                    "timestamp_ms": self.env.now,
                    "model": "sender",
                    "type": "timeout",
                    "val": {"seq": self.current_seq}
                })
                
                # Retransmit
                is_retry = True
                self.subnet_out.put(packet, "sender", "server_receiver")
                self.event_queue.append({
                    "timestamp_ms": self.env.now,
                    "model": "sender",
                    "type": "packet_sent",
                    "val": {"seq": packet.seq, "bit": packet.bit, "is_retry": is_retry}
                })
                
                # Wait again for ACK
                self.ack_event = self.env.event()
                self.received_ack = None
                
                def _wait_for_ack_retry():
                    ack_packet, source, dest = yield self.subnet_in.get()
                    self.received_ack = ack_packet
                    if self.ack_event and not self.ack_event.triggered:
                        self.ack_event.succeed()
                
                self.env.process(_wait_for_ack_retry())
                
                timeout_event = self.env.timeout(20000)
                result = yield self.ack_event | timeout_event
                
                if self.ack_event in result:
                    # ACK received after retry
                    ack_bit = self.received_ack.bit
                    self.event_queue.append({
                        "timestamp_ms": self.env.now,
                        "model": "sender",
                        "type": "ack_received",
                        "val": {"bit": ack_bit}
                    })
                    
                    if ack_bit == self.current_bit:
                        # Correct ACK, advance
                        self.current_bit = 1 - self.current_bit
                        self.current_seq += 1
                        self.packets_remaining -= 1
                else:
                    # Timeout again, log and continue
                    self.event_queue.append({
                        "timestamp_ms": self.env.now,
                        "model": "sender",
                        "type": "timeout",
                        "val": {"seq": self.current_seq}
                    })
                    continue
            
            self.waiting_for_ack = False
            self.ack_event = None
        
        # All packets sent, mark as idle
        self.is_busy = False
        self.upload_process = None


class ServerReceiver:
    """Receives packets from sender, processes and stores them."""
    def __init__(self, env, subnet_in, subnet_out, storage_queue, event_queue):
        self.env = env
        self.subnet_in = subnet_in
        self.subnet_out = subnet_out
        self.storage_queue = storage_queue
        self.event_queue = event_queue
        self.expected_bit = 0
    
    def receive_loop(self):
        """Main receive loop."""
        while True:
            packet, source, dest = yield self.subnet_in.get()
            
            self.event_queue.append({
                "timestamp_ms": self.env.now,
                "model": "server_receiver",
                "type": "packet_received",
                "val": {"seq": packet.seq, "bit": packet.bit}
            })
            
            # Processing delay (3s)
            yield self.env.timeout(3000)
            
            # Check bit and send ACK
            if packet.bit == self.expected_bit:
                # New packet
                ack_bit = packet.bit
                self.storage_queue.append(packet)
                self.expected_bit = 1 - self.expected_bit
            else:
                # Duplicate, send ACK with previous bit
                ack_bit = 1 - packet.bit
            
            # Send ACK
            ack_packet = Packet(0, ack_bit)
            self.subnet_out.put(ack_packet, "server_receiver", "sender")
            
            self.event_queue.append({
                "timestamp_ms": self.env.now,
                "model": "server_receiver",
                "type": "ack_sent_to_sender",
                "val": {"bit": ack_bit}
            })


class ServerSender:
    """Sends packets from storage queue to receiver using ABP."""
    def __init__(self, env, subnet_out, subnet_in, storage_queue, event_queue):
        self.env = env
        self.subnet_out = subnet_out
        self.subnet_in = subnet_in
        self.storage_queue = storage_queue
        self.event_queue = event_queue
        
        self.download_allowed = False
        self.current_packet = None
        self.waiting_for_ack = False
    
    def handle_request(self, allowed):
        """Handle request command to toggle download permission."""
        self.download_allowed = allowed
        self.event_queue.append({
            "timestamp_ms": self.env.now,
            "model": "server_sender",
            "type": "download_valve_change",
            "val": {"allowed": allowed}
        })
        
        if allowed and not self.waiting_for_ack and self.storage_queue:
            self.env.process(self.download_loop())
    
    def download_loop(self):
        """Main download loop."""
        while self.download_allowed and self.storage_queue and not self.waiting_for_ack:
            # Get packet from storage
            self.current_packet = self.storage_queue.popleft()
            
            # Send packet (no processing delay)
            self.subnet_out.put(self.current_packet, "server_sender", "receiver")
            
            self.event_queue.append({
                "timestamp_ms": self.env.now,
                "model": "server_sender",
                "type": "packet_forwarded",
                "val": {"seq": self.current_packet.seq, "bit": self.current_packet.bit}
            })
            
            # Wait for ACK
            self.waiting_for_ack = True
            
            try:
                ack_packet, source, dest = yield self.subnet_in.get()
                
                self.event_queue.append({
                    "timestamp_ms": self.env.now,
                    "model": "server_sender",
                    "type": "ack_received_from_receiver",
                    "val": {"bit": ack_packet.bit}
                })
                
                self.waiting_for_ack = False
                self.current_packet = None
                
            except Exception as e:
                logger.error(f"Error in server sender download loop: {e}")
                self.waiting_for_ack = False
                self.current_packet = None


class Receiver:
    """Receives packets from server, processes and sends ACK."""
    def __init__(self, env, subnet_in, subnet_out, event_queue):
        self.env = env
        self.subnet_in = subnet_in
        self.subnet_out = subnet_out
        self.event_queue = event_queue
    
    def receive_loop(self):
        """Main receive loop."""
        while True:
            packet, source, dest = yield self.subnet_in.get()
            
            # Processing delay (10s)
            self.event_queue.append({
                "timestamp_ms": self.env.now,
                "model": "receiver",
                "type": "processing_started",
                "val": {"seq": packet.seq, "duration": 10000}
            })
            
            yield self.env.timeout(10000)
            
            # Send ACK
            ack_packet = Packet(0, packet.bit)
            self.subnet_out.put(ack_packet, "receiver", "server_sender")
            
            self.event_queue.append({
                "timestamp_ms": self.env.now,
                "model": "receiver",
                "type": "ack_sent",
                "val": {"bit": packet.bit}
            })


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


def read_commands():
    """Read commands from stdin."""
    commands = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 3:
            time_str = parts[0]
            cmd_type = parts[1]
            value = parts[2]
            commands.append({
                'time_ms': parse_time(time_str),
                'type': cmd_type,
                'value': int(value)
            })
    return commands


def main():
    parser = argparse.ArgumentParser(description='Dropbox-like synchronization simulation')
    parser.add_argument('--simulation_time', type=float, default=10000000.0,
                        help='Simulation duration in milliseconds')
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    event_queue = []
    
    # Create storage queue
    storage_queue = deque()
    
    # Create subnets (3s delay each)
    subnet_a1 = Subnet(env, "A1", 3000)  # Sender -> Server
    subnet_a2 = Subnet(env, "A2", 3000)  # Server -> Sender
    subnet_b1 = Subnet(env, "B1", 3000)  # Server -> Receiver
    subnet_b2 = Subnet(env, "B2", 3000)  # Receiver -> Server
    
    # Create entities
    sender = Sender(env, subnet_a1, subnet_a2, event_queue)
    server_receiver = ServerReceiver(env, subnet_a1, subnet_a2, storage_queue, event_queue)
    server_sender = ServerSender(env, subnet_b1, subnet_b2, storage_queue, event_queue)
    receiver = Receiver(env, subnet_b1, subnet_b2, event_queue)
    
    # Start entity processes
    env.process(server_receiver.receive_loop())
    env.process(receiver.receive_loop())
    
    # Read commands from stdin
    commands = read_commands()
    
    # Schedule commands
    for cmd in commands:
        def _schedule_command(c=cmd):
            yield env.timeout(c['time_ms'])
            if c['type'] == 'control':
                sender.handle_control(c['value'])
            elif c['type'] == 'request':
                server_sender.handle_request(c['value'])
        
        env.process(_schedule_command(cmd))
    
    # Run simulation
    logger.info(f"Starting simulation for {args.simulation_time} ms")
    env.run(until=args.simulation_time)
    logger.info("Simulation completed")
    
    # Sort events by timestamp and output
    event_queue.sort(key=lambda x: x['timestamp_ms'])
    for event in event_queue:
        print(json.dumps(event))


if __name__ == '__main__':
    main()