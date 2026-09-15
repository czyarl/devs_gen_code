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


# Global constants
SIMULATION_TIME = 10000.0  # 10 seconds in milliseconds
SENDER_PREPARE_TIME = 10000.0  # 10 seconds
SERVER_PROCESSING_TIME = 3000.0  # 3 seconds
RECEIVER_PROCESSING_TIME = 10000.0  # 10 seconds
ABP_TIMEOUT = 20000.0  # 20 seconds
SUBNET_DELAY = 3000.0  # 3 seconds


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
    """Simulates a network subnet with fixed delay."""
    def __init__(self, env: simpy.Environment, delay: float, name: str):
        self.env = env
        self.delay = delay
        self.name = name

    def send(self, packet: Packet, target):
        """Send packet through subnet with delay."""
        yield self.env.timeout(self.delay)
        target.receive(packet)


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
        self.is_busy = False
        self.ack_events = {}  # Store ack events for each packet

    def control_cmd(self, added_packets: int):
        """Handle control command to add packets to upload queue."""
        self.total_packets_to_send += added_packets
        self.packets_remaining = self.total_packets_to_send
        
        # Log the control command
        event = Event(self.env.now, "sender", "control_cmd", {
            "added": added_packets,
            "total_remaining": self.total_packets_to_send
        })
        print(event.to_json(), file=sys.stderr)
        
        # If sender is idle, start uploading
        if not self.is_busy:
            self.env.process(self.upload_loop())

    def upload_loop(self):
        """Main upload loop for the sender."""
        self.is_busy = True
        
        while self.packets_remaining > 0:
            # Prepare for sending (10s delay)
            event = Event(self.env.now, "sender", "preparation_started", {
                "duration": SENDER_PREPARE_TIME
            })
            print(event.to_json(), file=sys.stderr)
            
            yield self.env.timeout(SENDER_PREPARE_TIME)
            
            # Send packet
            packet = Packet(self.current_seq, self.current_bit)
            event = Event(self.env.now, "sender", "packet_sent", {
                "seq": self.current_seq,
                "bit": self.current_bit,
                "is_retry": False
            })
            print(event.to_json(), file=sys.stderr)
            
            # Create event to wait for ACK
            ack_event = self.env.event()
            self.ack_events[self.current_seq] = ack_event
            
            # Send packet to server
            yield from self.subnet_a1.send(packet, self.server_receiver)
            
            # Wait for ACK with timeout
            timeout_event = self.env.timeout(ABP_TIMEOUT)
            results = yield ack_event | timeout_event
            
            if ack_event in results:
                # Correct ACK received
                event = Event(self.env.now, "sender", "ack_received", {
                    "bit": self.current_bit
                })
                print(event.to_json(), file=sys.stderr)
                
                # Update state
                self.current_bit = 1 - self.current_bit  # Flip bit
                self.current_seq += 1
                self.packets_remaining -= 1
                # Clean up the event
                del self.ack_events[self.current_seq - 1]
            else:
                # Timeout occurred
                event = Event(self.env.now, "sender", "timeout", {
                    "seq": self.current_seq
                })
                print(event.to_json(), file=sys.stderr)
                
                # Retry sending the same packet
                packet = Packet(self.current_seq, self.current_bit)
                event = Event(self.env.now, "sender", "packet_sent", {
                    "seq": self.current_seq,
                    "bit": self.current_bit,
                    "is_retry": True
                })
                print(event.to_json(), file=sys.stderr)
                
                # Create new event to wait for ACK
                ack_event = self.env.event()
                self.ack_events[self.current_seq] = ack_event
                
                # Send packet to server
                yield from self.subnet_a1.send(packet, self.server_receiver)
                
                # Wait for ACK with timeout
                timeout_event = self.env.timeout(ABP_TIMEOUT)
                results = yield ack_event | timeout_event
                
                if ack_event in results:
                    # Correct ACK received
                    event = Event(self.env.now, "sender", "ack_received", {
                        "bit": self.current_bit
                    })
                    print(event.to_json(), file=sys.stderr)
                    
                    # Update state
                    self.current_bit = 1 - self.current_bit  # Flip bit
                    self.current_seq += 1
                    self.packets_remaining -= 1
                    # Clean up the event
                    del self.ack_events[self.current_seq - 1]
                else:
                    # Still no ACK, this should not happen in our simulation
                    pass
        
        self.is_busy = False

    def signal_ack(self, seq: int, bit: int):
        """Signal ACK to sender."""
        # Signal the ACK event to the sender
        if seq in self.ack_events:
            self.ack_events[seq].succeed()


class ServerReceiver:
    """Server component that receives packets from sender."""
    def __init__(self, env: simpy.Environment, server_sender, subnet_a2):
        self.env = env
        self.server_sender = server_sender
        self.subnet_a2 = subnet_a2
        self.expected_bit = 0
        self.storage_queue = deque()

    def receive(self, packet: Packet):
        """Receive packet from sender."""
        # Log packet arrival
        event = Event(self.env.now, "server_receiver", "packet_received", {
            "seq": packet.seq,
            "bit": packet.bit
        })
        print(event.to_json(), file=sys.stderr)
        
        # Process with 3s delay
        yield self.env.timeout(SERVER_PROCESSING_TIME)
        
        # Check if packet is valid
        if packet.bit == self.expected_bit:
            # Valid packet
            self.storage_queue.append(packet)
            
            # Send ACK back to sender
            ack_packet = Packet(packet.seq, packet.bit)
            event = Event(self.env.now, "server_receiver", "ack_sent_to_sender", {
                "bit": packet.bit
            })
            print(event.to_json(), file=sys.stderr)
            
            # Send ACK to sender
            yield from self.subnet_a2.send(ack_packet, self.server_sender)
            
            # Signal ACK to sender
            self.server_sender.signal_ack(packet.seq, packet.bit)
            
            # Flip expected bit
            self.expected_bit = 1 - self.expected_bit
        else:
            # Duplicate packet - resend ACK
            ack_packet = Packet(packet.seq, 1 - packet.bit)
            event = Event(self.env.now, "server_receiver", "ack_sent_to_sender", {
                "bit": 1 - packet.bit
            })
            print(event.to_json(), file=sys.stderr)
            
            # Send ACK to sender
            yield from self.subnet_a2.send(ack_packet, self.server_sender)
            
            # Signal ACK to sender
            self.server_sender.signal_ack(packet.seq, 1 - packet.bit)


class ServerSender:
    """Server component that forwards packets to receiver."""
    def __init__(self, env: simpy.Environment, receiver, subnet_b1):
        self.env = env
        self.receiver = receiver
        self.subnet_b1 = subnet_b1
        self.download_allowed = False
        self.storage_queue = deque()
        self.is_sending = False
        self.current_packet = None
        self.current_ack_event = None

    def download_valve_change(self, allowed: bool):
        """Handle download valve change."""
        self.download_allowed = allowed
        
        # Log the change
        event = Event(self.env.now, "server_sender", "download_valve_change", {
            "allowed": allowed
        })
        print(event.to_json(), file=sys.stderr)
        
        # If download is allowed and we have packets, start sending
        if allowed and self.storage_queue:
            self.env.process(self.forward_loop())

    def receive_from_storage(self, packet: Packet):
        """Receive packet from storage queue."""
        self.storage_queue.append(packet)
        
        # If download is allowed and not currently sending, start sending
        if self.download_allowed and not self.is_sending and self.storage_queue:
            self.env.process(self.forward_loop())

    def forward_loop(self):
        """Main forward loop for the server sender."""
        self.is_sending = True
        
        while self.storage_queue and self.download_allowed:
            # Get packet from storage
            packet = self.storage_queue.popleft()
            self.current_packet = packet
            
            # Send packet to receiver
            event = Event(self.env.now, "server_sender", "packet_forwarded", {
                "seq": packet.seq,
                "bit": packet.bit
            })
            print(event.to_json(), file=sys.stderr)
            
            # Create event to wait for ACK
            ack_event = self.env.event()
            
            # Send packet to receiver
            yield from self.subnet_b1.send(packet, self.receiver)
            
            # Wait for ACK from receiver with timeout
            timeout_event = self.env.timeout(ABP_TIMEOUT)
            results = yield ack_event | timeout_event
            
            if ack_event in results:
                # Correct ACK received
                event = Event(self.env.now, "server_sender", "ack_received_from_receiver", {
                    "bit": packet.bit
                })
                print(event.to_json(), file=sys.stderr)
            else:
                # Timeout or error - this shouldn't happen in our simulation
                pass
        
        self.is_sending = False


class Receiver:
    """Receiver entity that downloads packets from server."""
    def __init__(self, env: simpy.Environment, server_sender, subnet_b2):
        self.env = env
        self.server_sender = server_sender
        self.subnet_b2 = subnet_b2

    def receive(self, packet: Packet):
        """Receive packet from server."""
        # Log processing start
        event = Event(self.env.now, "receiver", "processing_started", {
            "seq": packet.seq,
            "duration": RECEIVER_PROCESSING_TIME
        })
        print(event.to_json(), file=sys.stderr)
        
        # Process with 10s delay
        yield self.env.timeout(RECEIVER_PROCESSING_TIME)
        
        # Send ACK back to server
        ack_packet = Packet(packet.seq, packet.bit)
        event = Event(self.env.now, "receiver", "ack_sent", {
            "bit": packet.bit
        })
        print(event.to_json(), file=sys.stderr)
        
        # Send ACK to server
        yield from self.subnet_b2.send(ack_packet, self.server_sender)


def parse_time(time_str: str) -> float:
    """Parse time string in format HH:MM:SS:mmm to milliseconds."""
    h, m, s, ms = map(int, time_str.split(':'))
    return (h * 3600 + m * 60 + s) * 1000 + ms


def main():
    """Main simulation function."""
    parser = argparse.ArgumentParser(description='Dropbox-like synchronization simulation')
    parser.add_argument('--simulation_time', type=float, default=SIMULATION_TIME,
                        help='Simulation duration in milliseconds (default: 10000.0)')
    
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create components
    subnet_a1 = Subnet(env, SUBNET_DELAY, "A1")
    subnet_a2 = Subnet(env, SUBNET_DELAY, "A2")
    subnet_b1 = Subnet(env, SUBNET_DELAY, "B1")
    subnet_b2 = Subnet(env, SUBNET_DELAY, "B2")
    
    # Create server components
    server_sender = ServerSender(env, None, subnet_b1)
    server_receiver = ServerReceiver(env, server_sender, subnet_a2)
    
    # Create sender and receiver
    sender = Sender(env, server_receiver, subnet_a1)
    receiver = Receiver(env, server_sender, subnet_b2)
    
    # Update server components with references to each other
    server_sender.receiver = receiver
    server_receiver.server_sender = server_sender
    
    # Process input from stdin
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
            
        parts = line.split()
        if len(parts) < 3:
            continue
            
        timestamp_str = parts[0]
        event_type = parts[1]
        value = parts[2]
        
        timestamp = parse_time(timestamp_str)
        
        # Schedule the event
        if event_type == "control":
            env.process(delayed_control(env, timestamp, sender, int(value)))
        elif event_type == "request":
            env.process(delayed_request(env, timestamp, server_sender, int(value)))
    
    # Run simulation
    env.run(until=args.simulation_time)
    
    # Print final state
    final_state = {
        "timestamp_ms": args.simulation_time,
        "model": "final_state",
        "type": "simulation_end",
        "val": {}
    }
    print(json.dumps(final_state))


def delayed_control(env: simpy.Environment, timestamp: float, sender: Sender, added_packets: int):
    """Delay control command until specified time."""
    yield env.timeout(timestamp - env.now)
    sender.control_cmd(added_packets)


def delayed_request(env: simpy.Environment, timestamp: float, server_sender: ServerSender, allowed: int):
    """Delay request command until specified time."""
    yield env.timeout(timestamp - env.now)
    server_sender.download_valve_change(bool(allowed))


if __name__ == "__main__":
    main()