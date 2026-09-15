#!/usr/bin/env python3
"""
Dropbox-like synchronization simulation using Alternating Bit Protocol (ABP).
Two independent loops: Upload (Sender -> Server) and Download (Server -> Receiver).
"""

import argparse
import sys
import json
import logging
from collections import deque
import simpy

# Configure logging
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
    """Reliable FIFO channel with fixed delay."""
    def __init__(self, env, name, delay_ms):
        self.env = env
        self.name = name
        self.delay_ms = delay_ms
        self.store = simpy.Store(env)
    
    def send(self, packet, source, destination):
        """Send packet through subnet with fixed delay."""
        def _transmit():
            yield self.env.timeout(self.delay_ms)
            yield self.store.put((packet, source, destination))
        
        self.env.process(_transmit())
    
    def receive(self):
        """Receive packet from subnet."""
        return self.store.get()


class Sender:
    """Uploads packets to server using ABP."""
    def __init__(self, env, subnet_a1, subnet_a2, event_queue):
        self.env = env
        self.subnet_a1 = subnet_a1  # To server
        self.subnet_a2 = subnet_a2  # From server
        self.event_queue = event_queue
        
        self.total_packets_to_send = 0
        self.packets_remaining = 0
        self.current_seq = 1
        self.current_bit = 0
        self.is_idle = True
        self.waiting_for_ack = False
        self.last_packet_sent = None
        self.retry_count = 0
    
    def handle_control(self, added_packets):
        """Handle control command to add packets to upload queue."""
        self.total_packets_to_send += added_packets
        self.packets_remaining += added_packets
        
        self.event_queue.append({
            "timestamp_ms": self.env.now,
            "model": "sender",
            "type": "control_cmd",
            "val": {"added": added_packets, "total_remaining": self.packets_remaining}
        })
        
        logger.info(f"Sender: control command received, added={added_packets}, total_remaining={self.packets_remaining}")
        
        if self.is_idle and self.packets_remaining > 0:
            self.is_idle = False
            self.env.process(self.upload_loop())
    
    def upload_loop(self):
        """Main upload loop using ABP."""
        while self.packets_remaining > 0:
            # Preparation phase (10s)
            self.event_queue.append({
                "timestamp_ms": self.env.now,
                "model": "sender",
                "type": "preparation_started",
                "val": {"duration": 10000}
            })
            logger.info(f"Sender: preparation started for packet seq={self.current_seq}")
            
            yield self.env.timeout(10000)
            
            # Send packet
            packet = Packet(self.current_seq, self.current_bit)
            self.last_packet_sent = packet
            is_retry = self.retry_count > 0
            
            self.event_queue.append({
                "timestamp_ms": self.env.now,
                "model": "sender",
                "type": "packet_sent",
                "val": {"seq": packet.seq, "bit": packet.bit, "is_retry": is_retry}
            })
            logger.info(f"Sender: packet sent seq={packet.seq}, bit={packet.bit}, is_retry={is_retry}")
            
            self.subnet_a1.send(packet, "sender", "server_receiver")
            self.waiting_for_ack = True
            
            # Wait for ACK with timeout (20s)
            ack_received = False
            while not ack_received:
                # Wait for either ACK or timeout
                timeout_event = self.env.timeout(20000)
                receive_event = self.subnet_a2.receive()
                
                result = yield self.env.any_of([timeout_event, receive_event])
                
                if timeout_event in result:
                    # Timeout occurred
                    self.event_queue.append({
                        "timestamp_ms": self.env.now,
                        "model": "sender",
                        "type": "timeout",
                        "val": {"seq": self.current_seq}
                    })
                    logger.info(f"Sender: timeout for packet seq={self.current_seq}")
                    
                    self.retry_count += 1
                    # Retransmit
                    packet = Packet(self.current_seq, self.current_bit)
                    self.last_packet_sent = packet
                    
                    self.event_queue.append({
                        "timestamp_ms": self.env.now,
                        "model": "sender",
                        "type": "packet_sent",
                        "val": {"seq": packet.seq, "bit": packet.bit, "is_retry": True}
                    })
                    logger.info(f"Sender: retransmitting packet seq={packet.seq}, bit={packet.bit}")
                    
                    self.subnet_a1.send(packet, "sender", "server_receiver")
                else:
                    # ACK received
                    ack_packet, source, dest = receive_event.value
                    
                    if ack_packet.bit == self.current_bit:
                        # Correct ACK received
                        self.event_queue.append({
                            "timestamp_ms": self.env.now,
                            "model": "sender",
                            "type": "ack_received",
                            "val": {"bit": ack_packet.bit}
                        })
                        logger.info(f"Sender: ACK received bit={ack_packet.bit}")
                        
                        ack_received = True
                        self.waiting_for_ack = False
                        self.retry_count = 0
                        
                        # Flip bit and increment seq
                        self.current_bit = 1 - self.current_bit
                        self.current_seq += 1
                        self.packets_remaining -= 1
                    else:
                        # Wrong ACK, ignore and wait again
                        logger.info(f"Sender: received wrong ACK bit={ack_packet.bit}, expected={self.current_bit}")
                        continue
        
        # All packets sent
        self.is_idle = True
        logger.info("Sender: all packets sent, going idle")


class ServerReceiver:
    """Receives packets from Sender, processes them, and stores in queue."""
    def __init__(self, env, subnet_a1, subnet_a2, storage_queue, event_queue, server_sender=None):
        self.env = env
        self.subnet_a1 = subnet_a1  # From sender
        self.subnet_a2 = subnet_a2  # To sender
        self.storage_queue = storage_queue
        self.event_queue = event_queue
        self.server_sender = server_sender
        
        self.expected_bit = 0
    
    def receive_loop(self):
        """Main receive loop."""
        while True:
            # Receive packet from sender
            packet, source, dest = yield self.subnet_a1.receive()
            
            self.event_queue.append({
                "timestamp_ms": self.env.now,
                "model": "server_receiver",
                "type": "packet_received",
                "val": {"seq": packet.seq, "bit": packet.bit}
            })
            logger.info(f"ServerReceiver: packet received seq={packet.seq}, bit={packet.bit}")
            
            # Processing delay (3s)
            yield self.env.timeout(3000)
            
            # Check bit and send ACK
            if packet.bit == self.expected_bit:
                # New packet
                ack_packet = Packet(0, packet.bit)
                self.subnet_a2.send(ack_packet, "server_receiver", "sender")
                
                self.event_queue.append({
                    "timestamp_ms": self.env.now,
                    "model": "server_receiver",
                    "type": "ack_sent_to_sender",
                    "val": {"bit": packet.bit}
                })
                logger.info(f"ServerReceiver: ACK sent bit={packet.bit}")
                
                # Store packet
                self.storage_queue.append(packet)
                logger.info(f"ServerReceiver: packet stored in queue, queue size={len(self.storage_queue)}")
                
                # Notify ServerSender to check if it should start sending
                if self.server_sender:
                    self.server_sender.check_and_start_send()
                
                # Flip expected bit
                self.expected_bit = 1 - self.expected_bit
            else:
                # Duplicate packet, resend previous ACK
                ack_packet = Packet(0, 1 - packet.bit)
                self.subnet_a2.send(ack_packet, "server_receiver", "sender")
                
                self.event_queue.append({
                    "timestamp_ms": self.env.now,
                    "model": "server_receiver",
                    "type": "ack_sent_to_sender",
                    "val": {"bit": 1 - packet.bit}
                })
                logger.info(f"ServerReceiver: duplicate packet, resending ACK bit={1 - packet.bit}")


class ServerSender:
    """Sends packets from storage queue to Receiver using ABP."""
    def __init__(self, env, subnet_b1, subnet_b2, storage_queue, event_queue):
        self.env = env
        self.subnet_b1 = subnet_b1  # To receiver
        self.subnet_b2 = subnet_b2  # From receiver
        self.storage_queue = storage_queue
        self.event_queue = event_queue
        
        self.download_allowed = False
        self.current_bit = 0
        self.waiting_for_ack = False
        self.current_packet = None
        self.send_loop_process = None
    
    def handle_request(self, allowed):
        """Handle request command to toggle download permission."""
        self.download_allowed = allowed
        
        self.event_queue.append({
            "timestamp_ms": self.env.now,
            "model": "server_sender",
            "type": "download_valve_change",
            "val": {"allowed": allowed}
        })
        logger.info(f"ServerSender: download valve changed to allowed={allowed}")
        
        if allowed and not self.waiting_for_ack and self.storage_queue:
            if self.send_loop_process is None or not self.send_loop_process.is_alive:
                self.send_loop_process = self.env.process(self.send_loop())
    
    def check_and_start_send(self):
        """Check if we should start sending packets."""
        if self.download_allowed and not self.waiting_for_ack and self.storage_queue:
            if self.send_loop_process is None or not self.send_loop_process.is_alive:
                self.send_loop_process = self.env.process(self.send_loop())
    
    def send_loop(self):
        """Main send loop using ABP."""
        while self.download_allowed and self.storage_queue and not self.waiting_for_ack:
            # Get packet from queue
            packet = self.storage_queue.popleft()
            self.current_packet = packet
            
            self.event_queue.append({
                "timestamp_ms": self.env.now,
                "model": "server_sender",
                "type": "packet_forwarded",
                "val": {"seq": packet.seq, "bit": packet.bit}
            })
            logger.info(f"ServerSender: packet forwarded seq={packet.seq}, bit={packet.bit}")
            
            self.subnet_b1.send(packet, "server_sender", "receiver")
            self.waiting_for_ack = True
            
            # Wait for ACK
            ack_packet, source, dest = yield self.subnet_b2.receive()
            
            self.event_queue.append({
                "timestamp_ms": self.env.now,
                "model": "server_sender",
                "type": "ack_received_from_receiver",
                "val": {"bit": ack_packet.bit}
            })
            logger.info(f"ServerSender: ACK received from receiver bit={ack_packet.bit}")
            
            self.waiting_for_ack = False
            self.current_packet = None
        
        logger.info("ServerSender: send loop finished")


class Receiver:
    """Receives packets from Server, processes them, and sends ACK."""
    def __init__(self, env, subnet_b1, subnet_b2, event_queue):
        self.env = env
        self.subnet_b1 = subnet_b1  # From server
        self.subnet_b2 = subnet_b2  # To server
        self.event_queue = event_queue
    
    def receive_loop(self):
        """Main receive loop."""
        while True:
            # Receive packet from server
            packet, source, dest = yield self.subnet_b1.receive()
            
            # Processing delay (10s)
            self.event_queue.append({
                "timestamp_ms": self.env.now,
                "model": "receiver",
                "type": "processing_started",
                "val": {"seq": packet.seq, "duration": 10000}
            })
            logger.info(f"Receiver: processing started for packet seq={packet.seq}")
            
            yield self.env.timeout(10000)
            
            # Send ACK
            ack_packet = Packet(0, packet.bit)
            self.subnet_b2.send(ack_packet, "receiver", "server_sender")
            
            self.event_queue.append({
                "timestamp_ms": self.env.now,
                "model": "receiver",
                "type": "ack_sent",
                "val": {"bit": packet.bit}
            })
            logger.info(f"Receiver: ACK sent bit={packet.bit}")


def parse_time(time_str):
    """Parse time string to milliseconds."""
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


def schedule_commands(env, sender, server_sender, commands):
    """Schedule commands from stdin."""
    for time_str, cmd_type, value in commands:
        delay_ms = parse_time(time_str)
        
        def _execute_command(delay=delay_ms, t=cmd_type, v=value):
            yield env.timeout(delay)
            if t == "control":
                sender.handle_control(int(v))
            elif t == "request":
                server_sender.handle_request(int(v) == 1)
        
        env.process(_execute_command())


def main():
    parser = argparse.ArgumentParser(description='Dropbox-like synchronization simulation')
    parser.add_argument('--simulation_time', type=float, default=10000000.0,
                        help='Simulation duration in milliseconds')
    args = parser.parse_args()
    
    # Read commands from stdin
    commands = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 3:
            time_str, cmd_type, value = parts[0], parts[1], parts[2]
            commands.append((time_str, cmd_type, value))
    
    logger.info(f"Read {len(commands)} commands from stdin")
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Event queue for JSON output
    event_queue = []
    
    # Create subnets (3s delay)
    subnet_a1 = Subnet(env, "A1", 3000)  # Sender -> Server
    subnet_a2 = Subnet(env, "A2", 3000)  # Server -> Sender
    subnet_b1 = Subnet(env, "B1", 3000)  # Server -> Receiver
    subnet_b2 = Subnet(env, "B2", 3000)  # Receiver -> Server
    
    # Create storage queue
    storage_queue = deque()
    
    # Create components
    sender = Sender(env, subnet_a1, subnet_a2, event_queue)
    server_sender = ServerSender(env, subnet_b1, subnet_b2, storage_queue, event_queue)
    server_receiver = ServerReceiver(env, subnet_a1, subnet_a2, storage_queue, event_queue, server_sender)
    receiver = Receiver(env, subnet_b1, subnet_b2, event_queue)
    
    # Start component processes
    env.process(server_receiver.receive_loop())
    env.process(receiver.receive_loop())
    
    # Schedule commands
    schedule_commands(env, sender, server_sender, commands)
    
    # Run simulation
    logger.info(f"Starting simulation for {args.simulation_time} ms")
    env.run(until=args.simulation_time)
    logger.info("Simulation completed")
    
    # Sort events by timestamp and output as JSONL
    event_queue.sort(key=lambda x: x["timestamp_ms"])
    for event in event_queue:
        print(json.dumps(event))


if __name__ == "__main__":
    main()