#!/usr/bin/env python3
"""
Dropbox-like synchronization simulation using Alternating Bit Protocol (ABP)
with two independent ABP loops: Upload (Sender -> Server) and Download (Server -> Receiver).
"""
import argparse
import sys
import json
import logging
from collections import deque
from typing import Optional, Deque
import simpy


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class Event:
    """Represents an event in the simulation."""
    def __init__(self, timestamp_ms: float, model: str, event_type: str, val: dict):
        self.timestamp_ms = timestamp_ms
        self.model = model
        self.type = event_type
        self.val = val

    def to_json(self) -> str:
        return json.dumps({
            "timestamp_ms": self.timestamp_ms,
            "model": self.model,
            "type": self.type,
            "val": self.val
        })


class Packet:
    """Represents a data packet in the ABP protocol."""
    def __init__(self, seq: int, bit: int, data: Optional[str] = None):
        self.seq = seq
        self.bit = bit
        self.data = data


class Subnet:
    """Simulates a network subnet with fixed delay and FIFO behavior."""
    def __init__(self, env: simpy.Environment, delay_ms: float, name: str):
        self.env = env
        self.delay_ms = delay_ms
        self.name = name

    def send(self, packet: Packet, destination):
        """Send packet through subnet with delay."""
        # Simulate transmission delay
        yield self.env.timeout(self.delay_ms)
        # Forward to destination
        destination.receive(packet)


class Sender:
    """Sender entity that uploads packets to the server."""
    def __init__(self, env: simpy.Environment, server_receiver, subnet_a1):
        self.env = env
        self.server_receiver = server_receiver
        self.subnet_a1 = subnet_a1
        self.packets_remaining = 0
        self.total_packets_to_send = 0
        self.current_bit = 0
        self.current_seq = 1
        self.is_idle = True
        self.timeout_duration = 20000  # 20 seconds in milliseconds
        self.preparation_duration = 10000  # 10 seconds in milliseconds

    def control_cmd(self, added_packets: int):
        """Handle control command to add packets to upload queue."""
        self.total_packets_to_send += added_packets
        self.packets_remaining = self.total_packets_to_send
        
        # Log the control command
        event = Event(
            self.env.now,
            "sender",
            "control_cmd",
            {"added": added_packets, "total_remaining": self.total_packets_to_send}
        )
        print(event.to_json())
        
        # If idle, start uploading
        if self.is_idle:
            self.is_idle = False
            self.env.process(self.upload_loop())

    def upload_loop(self):
        """Main upload loop for the sender."""
        while self.packets_remaining > 0:
            # Prepare for sending (10s delay)
            event = Event(
                self.env.now,
                "sender",
                "preparation_started",
                {"duration": self.preparation_duration}
            )
            print(event.to_json())
            
            yield self.env.timeout(self.preparation_duration)
            
            # Send packet
            packet = Packet(self.current_seq, self.current_bit)
            
            event = Event(
                self.env.now,
                "sender",
                "packet_sent",
                {"seq": packet.seq, "bit": packet.bit, "is_retry": False}
            )
            print(event.to_json())
            
            # Send packet to server and wait for ACK
            ack_event = self.env.event()
            yield self.env.process(self.send_packet_and_wait_ack(packet, ack_event))
            
            # Process ACK result
            if ack_event.triggered:
                ack_received = ack_event.value
                if ack_received:
                    # Correct ACK received
                    event = Event(
                        self.env.now,
                        "sender",
                        "ack_received",
                        {"bit": packet.bit}
                    )
                    print(event.to_json())
                    
                    # Update state
                    self.current_bit = 1 - self.current_bit  # Flip bit
                    self.current_seq += 1
                    self.packets_remaining -= 1
                else:
                    # Incorrect ACK or timeout
                    event = Event(
                        self.env.now,
                        "sender",
                        "timeout",
                        {"seq": packet.seq}
                    )
                    print(event.to_json())
                    
                    # Retransmit
                    self.retransmit_packet(packet)
            else:
                # Timeout occurred
                event = Event(
                    self.env.now,
                    "sender",
                    "timeout",
                    {"seq": packet.seq}
                )
                print(event.to_json())
                
                # Retransmit
                self.retransmit_packet(packet)

        # Done uploading
        self.is_idle = True
        self.total_packets_to_send = 0
        self.packets_remaining = 0

    def send_packet_and_wait_ack(self, packet: Packet, ack_event):
        """Send packet and wait for ACK with timeout."""
        # Send packet to server
        yield self.subnet_a1.send(packet, self.server_receiver)
        
        # Wait for either ACK or timeout
        timeout = self.env.timeout(self.timeout_duration)
        result = yield timeout | ack_event
        
        # Check if timeout occurred
        if timeout.triggered:
            # Timeout occurred
            ack_event.succeed(False)  # Signal timeout
        elif not ack_event.triggered:
            # ACK event not triggered, likely timeout
            ack_event.succeed(False)  # Signal timeout

    def retransmit_packet(self, packet: Packet):
        """Retransmit a packet."""
        # Send packet again
        packet = Packet(self.current_seq, self.current_bit)
        event = Event(
            self.env.now,
            "sender",
            "packet_sent",
            {"seq": packet.seq, "bit": packet.bit, "is_retry": True}
        )
        print(event.to_json())
        
        # Send packet to server and wait for ACK
        ack_event = self.env.event()
        yield self.env.process(self.send_packet_and_wait_ack(packet, ack_event))
        
        # Process ACK result
        if ack_event.triggered:
            ack_received = ack_event.value
            if ack_received:
                # Correct ACK received
                event = Event(
                    self.env.now,
                    "sender",
                    "ack_received",
                    {"bit": packet.bit}
                )
                print(event.to_json())
                
                # Update state
                self.current_bit = 1 - self.current_bit  # Flip bit
                self.current_seq += 1
                self.packets_remaining -= 1


class ServerReceiver:
    """Server component that receives packets from sender and stores them."""
    def __init__(self, env: simpy.Environment, server_sender, subnet_a2):
        self.env = env
        self.server_sender = server_sender
        self.subnet_a2 = subnet_a2
        self.expected_bit = 0
        self.storage_queue = deque()
        self.processing_delay = 3000  # 3 seconds in milliseconds

    def receive(self, packet: Packet):
        """Receive packet from sender."""
        # Log packet arrival
        event = Event(
            self.env.now,
            "server_receiver",
            "packet_received",
            {"seq": packet.seq, "bit": packet.bit}
        )
        print(event.to_json())
        
        # Process with delay
        yield self.env.timeout(self.processing_delay)
        
        # Check if packet is valid
        if packet.bit == self.expected_bit:
            # Valid packet
            self.storage_queue.append(packet)
            
            # Send ACK back to sender
            ack_packet = Packet(packet.seq, packet.bit)
            event = Event(
                self.env.now,
                "server_receiver",
                "ack_sent_to_sender",
                {"bit": ack_packet.bit}
            )
            print(event.to_json())
            
            # Send ACK to sender through subnet
            yield self.subnet_a2.send(ack_packet, self.server_sender)
            
            # Flip expected bit
            self.expected_bit = 1 - self.expected_bit
        else:
            # Duplicate packet - resend ACK
            ack_packet = Packet(packet.seq, 1 - packet.bit)  # Previous bit
            event = Event(
                self.env.now,
                "server_receiver",
                "ack_sent_to_sender",
                {"bit": ack_packet.bit}
            )
            print(event.to_json())
            
            # Send ACK to sender through subnet
            yield self.subnet_a2.send(ack_packet, self.server_sender)


class ServerSender:
    """Server component that forwards packets to receiver."""
    def __init__(self, env: simpy.Environment, receiver, subnet_b1):
        self.env = env
        self.receiver = receiver
        self.subnet_b1 = subnet_b1
        self.storage_queue = deque()
        self.download_allowed = False
        self.current_bit = 0
        self.timeout_duration = 20000  # 20 seconds in milliseconds

    def download_valve_change(self, allowed: bool):
        """Handle download valve change."""
        self.download_allowed = allowed
        
        event = Event(
            self.env.now,
            "server_sender",
            "download_valve_change",
            {"allowed": allowed}
        )
        print(event.to_json())
        
        # If download is allowed and we have packets, start sending
        if allowed and self.storage_queue:
            self.env.process(self.forward_loop())

    def receive_from_storage(self, packet: Packet):
        """Receive packet from storage queue."""
        self.storage_queue.append(packet)

    def forward_loop(self):
        """Forward packets to receiver if download is allowed."""
        while self.download_allowed and self.storage_queue:
            # Get packet from storage
            packet = self.storage_queue.popleft()
            
            # Send packet to receiver
            event = Event(
                self.env.now,
                "server_sender",
                "packet_forwarded",
                {"seq": packet.seq, "bit": packet.bit}
            )
            print(event.to_json())
            
            # Send packet to receiver and wait for ACK
            ack_event = self.env.event()
            yield self.env.process(self.send_packet_and_wait_ack(packet, ack_event))
            
            # Process ACK result
            if ack_event.triggered:
                ack_received = ack_event.value
                if ack_received:
                    # Correct ACK received
                    event = Event(
                        self.env.now,
                        "server_sender",
                        "ack_received_from_receiver",
                        {"bit": packet.bit}
                    )
                    print(event.to_json())
                    
                    # Update state
                    self.current_bit = 1 - self.current_bit
                else:
                    # Incorrect ACK or timeout
                    event = Event(
                        self.env.now,
                        "server_sender",
                        "timeout",
                        {"seq": packet.seq}
                    )
                    print(event.to_json())
                    
                    # Retransmit
                    self.retransmit_packet(packet)
            else:
                # Timeout occurred
                event = Event(
                    self.env.now,
                    "server_sender",
                    "timeout",
                    {"seq": packet.seq}
                )
                print(event.to_json())
                
                # Retransmit
                self.retransmit_packet(packet)

    def send_packet_and_wait_ack(self, packet: Packet, ack_event):
        """Send packet and wait for ACK with timeout."""
        # Send packet to receiver
        yield self.subnet_b1.send(packet, self.receiver)
        
        # Wait for either ACK or timeout
        timeout = self.env.timeout(self.timeout_duration)
        result = yield timeout | ack_event
        
        # Check if timeout occurred
        if timeout.triggered:
            # Timeout occurred
            ack_event.succeed(False)  # Signal timeout
        elif not ack_event.triggered:
            # ACK event not triggered, likely timeout
            ack_event.succeed(False)  # Signal timeout

    def retransmit_packet(self, packet: Packet):
        """Retransmit a packet."""
        # Send packet again
        event = Event(
            self.env.now,
            "server_sender",
            "packet_forwarded",
            {"seq": packet.seq, "bit": packet.bit}
        )
        print(event.to_json())
        
        # Send packet to receiver and wait for ACK
        ack_event = self.env.event()
        yield self.env.process(self.send_packet_and_wait_ack(packet, ack_event))
        
        # Process ACK result
        if ack_event.triggered:
            ack_received = ack_event.value
            if ack_received:
                # Correct ACK received
                event = Event(
                    self.env.now,
                    "server_sender",
                    "ack_received_from_receiver",
                    {"bit": packet.bit}
                )
                print(event.to_json())
                
                # Update state
                self.current_bit = 1 - self.current_bit


class Receiver:
    """Receiver entity that downloads packets from server."""
    def __init__(self, env: simpy.Environment, server_sender, subnet_b2):
        self.env = env
        self.server_sender = server_sender
        self.subnet_b2 = subnet_b2
        self.processing_delay = 10000  # 10 seconds in milliseconds

    def receive(self, packet: Packet):
        """Receive packet from server."""
        # Log processing start
        event = Event(
            self.env.now,
            "receiver",
            "processing_started",
            {"seq": packet.seq, "duration": self.processing_delay}
        )
        print(event.to_json())
        
        # Process with delay
        yield self.env.timeout(self.processing_delay)
        
        # Send ACK back to server
        ack_packet = Packet(packet.seq, packet.bit)
        event = Event(
            self.env.now,
            "receiver",
            "ack_sent",
            {"bit": ack_packet.bit}
        )
        print(event.to_json())
        
        # Send ACK to server through subnet
        yield self.subnet_b2.send(ack_packet, self.server_sender)


def parse_time(time_str: str) -> float:
    """Parse time string in format HH:MM:SS:mmm to milliseconds."""
    h, m, s, ms = map(int, time_str.split(':'))
    return (h * 3600 + m * 60 + s) * 1000 + ms


def main():
    parser = argparse.ArgumentParser(description='Dropbox-like synchronization simulation')
    parser.add_argument('--simulation_time', type=float, default=10000000.0,
                       help='Simulation duration in milliseconds (default: 10000000.0)')
    
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create components
    subnet_a1 = Subnet(env, 3000, "A1")  # Sender -> Server
    subnet_a2 = Subnet(env, 3000, "A2")  # Server -> Sender
    subnet_b1 = Subnet(env, 3000, "B1")  # Server -> Receiver
    subnet_b2 = Subnet(env, 3000, "B2")  # Receiver -> Server
    
    # Create entities
    server_receiver = ServerReceiver(env, None, subnet_a2)  # Will be connected later
    server_sender = ServerSender(env, None, subnet_b1)      # Will be connected later
    receiver = Receiver(env, server_sender, subnet_b2)
    sender = Sender(env, server_receiver, subnet_a1)
    
    # Connect server components
    server_receiver.server_sender = server_sender
    server_sender.receiver = receiver
    
    # Set up event processing
    def process_input_line(line: str):
        """Process input line from stdin."""
        parts = line.strip().split()
        if len(parts) < 3:
            return
            
        timestamp_str = parts[0]
        event_type = parts[1]
        value = parts[2]
        
        timestamp_ms = parse_time(timestamp_str)
        
        # Schedule the event
        if event_type == "control":
            env.process(delayed_control(env, timestamp_ms, int(value)))
        elif event_type == "request":
            env.process(delayed_request(env, timestamp_ms, int(value)))
    
    def delayed_control(env: simpy.Environment, timestamp_ms: float, added_packets: int):
        """Delay control command until appropriate time."""
        yield env.timeout(timestamp_ms - env.now)
        sender.control_cmd(added_packets)
    
    def delayed_request(env: simpy.Environment, timestamp_ms: float, allowed: int):
        """Delay request command until appropriate time."""
        yield env.timeout(timestamp_ms - env.now)
        server_sender.download_valve_change(bool(allowed))
    
    # Process input from stdin
    for line in sys.stdin:
        if line.strip():
            process_input_line(line)
    
    # Run simulation
    env.run(until=args.simulation_time)
    
    # Print final state
    final_state = {
        "timestamp_ms": args.simulation_time,
        "model": "final_state",
        "type": "simulation_ended",
        "val": {}
    }
    print(json.dumps(final_state))


if __name__ == "__main__":
    main()