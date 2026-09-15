#!/usr/bin/env python3
"""
Dropbox-like synchronization simulation using Alternating Bit Protocol (ABP)
"""

import argparse
import sys
import json
import logging
import collections
import random
import simpy

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global constants
SIMULATION_TIME = 10000.0  # Default simulation time in milliseconds
PACKET_PREPARE_TIME = 10000  # 10 seconds in milliseconds
SERVER_PROCESSING_TIME = 3000  # 3 seconds in milliseconds
RECEIVER_PROCESSING_TIME = 10000  # 10 seconds in milliseconds
ABP_TIMEOUT = 20000  # 20 seconds in milliseconds

class Packet:
    """Represents a data packet in the ABP protocol"""
    def __init__(self, seq, bit, data=None):
        self.seq = seq
        self.bit = bit
        self.data = data

class Event:
    """Represents an event in the simulation"""
    def __init__(self, timestamp_ms, model, event_type, val):
        self.timestamp_ms = timestamp_ms
        self.model = model
        self.type = event_type
        self.val = val

    def to_json(self):
        """Convert event to JSON string"""
        return json.dumps({
            "timestamp_ms": self.timestamp_ms,
            "model": self.model,
            "type": self.type,
            "val": self.val
        })

class Subnet:
    """Represents a network subnet with fixed delay"""
    def __init__(self, env, delay_ms, name):
        self.env = env
        self.delay_ms = delay_ms
        self.name = name

    def send(self, packet, destination):
        """Send packet through subnet with delay"""
        yield self.env.timeout(self.delay_ms)
        destination.receive(packet)

class Sender:
    """Sender (Uploader) component"""
    def __init__(self, env, server_receiver, subnet_a1, name="sender"):
        self.env = env
        self.server_receiver = server_receiver
        self.subnet_a1 = subnet_a1
        self.name = name
        self.packets_remaining = 0
        self.total_packets_to_send = 0
        self.current_bit = 0
        self.current_seq = 1
        self.is_busy = False
        self.waiting_for_ack = False
        self.packet_queue = collections.deque()
        
        # Start the sender process
        self.process = env.process(self._run())

    def control_cmd(self, added_packets):
        """Handle control command to add packets to upload queue"""
        self.total_packets_to_send += added_packets
        self.packets_remaining = self.total_packets_to_send
        
        # Log the control command
        event = Event(self.env.now, self.name, "control_cmd", {
            "added": added_packets,
            "total_remaining": self.total_packets_to_send
        })
        print(event.to_json(), file=sys.stderr)
        
        # If sender is idle, start sending
        if not self.is_busy:
            self.is_busy = True
            self.env.process(self._start_uploading())

    def _start_uploading(self):
        """Start the uploading process"""
        # Log preparation started
        event = Event(self.env.now, self.name, "preparation_started", {
            "duration": PACKET_PREPARE_TIME
        })
        print(event.to_json(), file=sys.stderr)
        
        # Wait for preparation time
        yield self.env.timeout(PACKET_PREPARE_TIME)
        
        # Start sending packets
        yield self.env.process(self._send_packet())

    def _send_packet(self):
        """Send a packet using ABP"""
        if self.packets_remaining <= 0:
            # No more packets to send
            self.is_busy = False
            return
            
        # Create packet
        packet = Packet(self.current_seq, self.current_bit)
        
        # Log packet sent
        event = Event(self.env.now, self.name, "packet_sent", {
            "seq": self.current_seq,
            "bit": self.current_bit,
            "is_retry": False
        })
        print(event.to_json(), file=sys.stderr)
        
        # Send packet to server
        self.waiting_for_ack = True
        self.env.process(self.subnet_a1.send(packet, self.server_receiver))
        
        # Wait for ACK or timeout
        timeout = self.env.timeout(ABP_TIMEOUT)
        ack_event = self.env.event()
        
        # Wait for either ACK or timeout
        yield timeout | ack_event
        
        if timeout.triggered:
            # Timeout occurred, retransmit
            event = Event(self.env.now, self.name, "timeout", {
                "seq": self.current_seq
            })
            print(event.to_json(), file=sys.stderr)
            
            # Retransmit packet
            self.env.process(self.subnet_a1.send(packet, self.server_receiver))
            # Wait for ACK or timeout again
            yield timeout | ack_event
            
            if timeout.triggered:
                # Still no ACK, this shouldn't happen in normal operation
                pass
            else:
                # ACK received
                self.waiting_for_ack = False
                self.packets_remaining -= 1
                self.current_bit = 1 - self.current_bit  # Flip bit
                self.current_seq += 1
                
                # Log ACK received
                event = Event(self.env.now, self.name, "ack_received", {
                    "bit": self.current_bit
                })
                print(event.to_json(), file=sys.stderr)
                
                # Continue sending if more packets
                if self.packets_remaining > 0:
                    yield self.env.process(self._send_packet())
        else:
            # ACK received
            self.waiting_for_ack = False
            self.packets_remaining -= 1
            self.current_bit = 1 - self.current_bit  # Flip bit
            self.current_seq += 1
            
            # Log ACK received
            event = Event(self.env.now, self.name, "ack_received", {
                "bit": self.current_bit
            })
            print(event.to_json(), file=sys.stderr)
            
            # Continue sending if more packets
            if self.packets_remaining > 0:
                yield self.env.process(self._send_packet())

    def receive_ack(self, bit):
        """Receive ACK from server"""
        if self.waiting_for_ack and bit == self.current_bit:
            # Correct ACK received
            self.waiting_for_ack = False
            self.packets_remaining -= 1
            self.current_bit = 1 - self.current_bit  # Flip bit
            self.current_seq += 1
            
            # Log ACK received
            event = Event(self.env.now, self.name, "ack_received", {
                "bit": self.current_bit
            })
            print(event.to_json(), file=sys.stderr)
            
            # Continue sending if more packets
            if self.packets_remaining > 0:
                self.env.process(self._send_packet())
        elif self.waiting_for_ack and bit != self.current_bit:
            # Duplicate ACK - retransmit
            packet = Packet(self.current_seq, self.current_bit)
            self.env.process(self.subnet_a1.send(packet, self.server_receiver))
            # Log retransmission
            event = Event(self.env.now, self.name, "packet_sent", {
                "seq": self.current_seq,
                "bit": self.current_bit,
                "is_retry": True
            })
            print(event.to_json(), file=sys.stderr)

    def _run(self):
        """Main sender process"""
        while True:
            # Wait for control commands or other events
            yield self.env.timeout(1000)  # Placeholder for actual event handling

class ServerReceiver:
    """Server receiver component (Ingress Logic)"""
    def __init__(self, env, sender, subnet_a2, storage_queue, name="server_receiver"):
        self.env = env
        self.sender = sender
        self.subnet_a2 = subnet_a2
        self.storage_queue = storage_queue
        self.name = name
        self.expected_bit = 0
        self.process = env.process(self._run())

    def receive(self, packet):
        """Receive packet from sender"""
        # Log packet received
        event = Event(self.env.now, self.name, "packet_received", {
            "seq": packet.seq,
            "bit": packet.bit
        })
        print(event.to_json(), file=sys.stderr)
        
        # Process with delay
        yield self.env.timeout(SERVER_PROCESSING_TIME)
        
        # Check if bit matches expected bit
        if packet.bit == self.expected_bit:
            # Correct packet
            self.expected_bit = 1 - self.expected_bit  # Flip expected bit
            
            # Send ACK back to sender
            ack_packet = Packet(packet.seq, packet.bit)
            self.env.process(self.subnet_a2.send(ack_packet, self.sender))
            
            # Log ACK sent
            event = Event(self.env.now, self.name, "ack_sent_to_sender", {
                "bit": packet.bit
            })
            print(event.to_json(), file=sys.stderr)
            
            # Store packet in queue
            self.storage_queue.append(packet)
        else:
            # Duplicate packet - resend ACK
            ack_packet = Packet(packet.seq, 1 - packet.bit)  # Previous bit
            self.env.process(self.subnet_a2.send(ack_packet, self.sender))
            
            # Log ACK sent (duplicate)
            event = Event(self.env.now, self.name, "ack_sent_to_sender", {
                "bit": 1 - packet.bit
            })
            print(event.to_json(), file=sys.stderr)

    def _run(self):
        """Main server receiver process"""
        while True:
            # Wait for packets
            yield self.env.timeout(1000)  # Placeholder for actual event handling

class ServerSender:
    """Server sender component (Egress Logic)"""
    def __init__(self, env, receiver, subnet_b1, storage_queue, name="server_sender"):
        self.env = env
        self.receiver = receiver
        self.subnet_b1 = subnet_b1
        self.storage_queue = storage_queue
        self.name = name
        self.download_allowed = False
        self.is_busy = False
        self.waiting_for_ack = False
        self.process = env.process(self._run())

    def download_valve_change(self, allowed):
        """Handle download valve change"""
        self.download_allowed = allowed
        
        # Log the change
        event = Event(self.env.now, self.name, "download_valve_change", {
            "allowed": allowed
        })
        print(event.to_json(), file=sys.stderr)

    def _run(self):
        """Main server sender process"""
        while True:
            # Check if download is allowed and there are packets to send
            if self.download_allowed and self.storage_queue and not self.is_busy:
                self.is_busy = True
                self.env.process(self._forward_packet())
            
            yield self.env.timeout(1000)  # Check periodically

    def _forward_packet(self):
        """Forward a packet to receiver"""
        if not self.storage_queue:
            self.is_busy = False
            return
            
        # Get packet from queue
        packet = self.storage_queue.popleft()
        
        # Log packet forwarded
        event = Event(self.env.now, self.name, "packet_forwarded", {
            "seq": packet.seq,
            "bit": packet.bit
        })
        print(event.to_json(), file=sys.stderr)
        
        # Send packet to receiver
        self.waiting_for_ack = True
        self.env.process(self.subnet_b1.send(packet, self.receiver))
        
        # Wait for ACK or timeout
        timeout = self.env.timeout(ABP_TIMEOUT)
        ack_event = self.env.event()
        
        # Wait for either ACK or timeout
        yield timeout | ack_event
        
        if timeout.triggered:
            # Timeout occurred
            # This should not happen in normal operation, but we handle it
            pass
        else:
            # ACK received
            self.waiting_for_ack = False
            
            # Log ACK received
            event = Event(self.env.now, self.name, "ack_received_from_receiver", {
                "bit": packet.bit
            })
            print(event.to_json(), file=sys.stderr)
            
            # Continue if more packets and download still allowed
            if self.download_allowed and self.storage_queue:
                self.env.process(self._forward_packet())
            else:
                self.is_busy = False

    def receive_ack(self, bit):
        """Receive ACK from receiver"""
        if self.waiting_for_ack:
            self.waiting_for_ack = False
            
            # Log ACK received
            event = Event(self.env.now, self.name, "ack_received_from_receiver", {
                "bit": bit
            })
            print(event.to_json(), file=sys.stderr)
            
            # Continue if more packets and download still allowed
            if self.download_allowed and self.storage_queue:
                self.env.process(self._forward_packet())
            else:
                self.is_busy = False

class Receiver:
    """Receiver (Downloader) component"""
    def __init__(self, env, server_sender, subnet_b2, name="receiver"):
        self.env = env
        self.server_sender = server_sender
        self.subnet_b2 = subnet_b2
        self.name = name
        self.process = env.process(self._run())

    def receive(self, packet):
        """Receive packet from server"""
        # Log processing started
        event = Event(self.env.now, self.name, "processing_started", {
            "seq": packet.seq,
            "duration": RECEIVER_PROCESSING_TIME
        })
        print(event.to_json(), file=sys.stderr)
        
        # Process with delay
        yield self.env.timeout(RECEIVER_PROCESSING_TIME)
        
        # Send ACK back to server
        ack_packet = Packet(packet.seq, packet.bit)
        self.env.process(self.subnet_b2.send(ack_packet, self.server_sender))
        
        # Log ACK sent
        event = Event(self.env.now, self.name, "ack_sent", {
            "bit": packet.bit
        })
        print(event.to_json(), file=sys.stderr)

    def _run(self):
        """Main receiver process"""
        while True:
            # Wait for packets
            yield self.env.timeout(1000)  # Placeholder for actual event handling

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='Dropbox-like synchronization simulation')
    parser.add_argument('--simulation_time', type=float, default=SIMULATION_TIME, 
                       help='Simulation duration in milliseconds (default: 10000.0)')
    return parser.parse_args()

def process_input(env, sender, server_sender):
    """Process input from stdin"""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
            
        try:
            # Parse input line: HH:MM:SS:mmm type value
            parts = line.split(' ', 3)
            timestamp_str = parts[0]
            event_type = parts[1]
            value = parts[2]
            
            # Convert timestamp to milliseconds
            time_parts = timestamp_str.split(':')
            if len(time_parts) == 4:
                # HH:MM:SS:mmm format
                hours, minutes, seconds, milliseconds = map(int, time_parts)
            else:
                # HH:MM:SS format
                hours, minutes, seconds = map(int, time_parts)
                milliseconds = 0
            
            # Convert to simulation time (milliseconds)
            sim_time = (hours * 3600 + minutes * 60 + seconds) * 1000 + milliseconds
            
            # Schedule the event
            if event_type == "control":
                # Add to sender's packet queue
                env.process(env.timeout(sim_time - env.now))
                sender.control_cmd(int(value))
            elif event_type == "request":
                # Change download permission
                env.process(env.timeout(sim_time - env.now))
                server_sender.download_valve_change(bool(int(value)))
        except Exception as e:
            # Log error but continue processing
            print(f"Error processing input line: {line}", file=sys.stderr)
            print(f"Error: {e}", file=sys.stderr)

def main():
    """Main entry point"""
    args = parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create storage queue
    storage_queue = collections.deque()
    
    # Create subnets
    subnet_a1 = Subnet(env, 3000, "A1")  # Sender -> Server
    subnet_a2 = Subnet(env, 3000, "A2")  # Server -> Sender
    subnet_b1 = Subnet(env, 3000, "B1")  # Server -> Receiver
    subnet_b2 = Subnet(env, 3000, "B2")  # Receiver -> Server
    
    # Create components
    sender = Sender(env, None, subnet_a1)
    server_receiver = ServerReceiver(env, sender, subnet_a2, storage_queue)
    server_sender = ServerSender(env, None, subnet_b1, storage_queue)
    receiver = Receiver(env, server_sender, subnet_b2)
    
    # Connect components
    sender.server_receiver = server_receiver
    server_sender.receiver = receiver
    
    # Process input from stdin
    env.process(process_input(env, sender, server_sender))
    
    # Run simulation
    env.run(until=args.simulation_time)

if __name__ == "__main__":
    main()