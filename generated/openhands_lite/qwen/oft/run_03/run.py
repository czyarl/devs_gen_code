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
    def __init__(self, seq: int, bit: int, data: str = ""):
        self.seq = seq
        self.bit = bit
        self.data = data


class Subnet:
    """Simulates a subnet with fixed 3s delay."""
    def __init__(self, env: simpy.Environment, name: str, delay: float = 3000.0):
        self.env = env
        self.name = name
        self.delay = delay  # in milliseconds

    def send(self, packet: Packet, target):
        """Send packet with delay."""
        yield self.env.timeout(self.delay)
        target.receive(packet)


class Sender:
    """Sender entity that uploads packets to the server."""
    def __init__(self, env: simpy.Environment, name: str, server_receiver):
        self.env = env
        self.name = name
        self.server_receiver = server_receiver
        self.packets_remaining = 0
        self.total_packets_to_send = 0
        self.current_bit = 0
        self.current_seq = 1
        self.is_busy = False
        self.timeout_duration = 20000.0  # 20 seconds
        self.preparation_duration = 10000.0  # 10 seconds

    def control_cmd(self, added: int):
        """Handle control command to add packets to upload queue."""
        self.total_packets_to_send += added
        self.packets_remaining = self.total_packets_to_send
        logger.info(f"Sender received control command: added {added} packets, total remaining: {self.packets_remaining}")
        
        # Emit event
        event = Event(self.env.now, "sender", "control_cmd", {
            "added": added,
            "total_remaining": self.packets_remaining
        })
        print(event.to_json())
        
        # Start sending if not already busy
        if not self.is_busy:
            self.is_busy = True
            self.env.process(self.upload_loop())

    def upload_loop(self):
        """Main upload loop for the sender."""
        while self.packets_remaining > 0:
            # Preparation phase
            logger.info(f"Sender preparing to send packet {self.current_seq}")
            event = Event(self.env.now, "sender", "preparation_started", {
                "duration": self.preparation_duration
            })
            print(event.to_json())
            
            yield self.env.timeout(self.preparation_duration)
            
            # Send packet
            packet = Packet(self.current_seq, self.current_bit)
            logger.info(f"Sender sending packet {self.current_seq} with bit {self.current_bit}")
            event = Event(self.env.now, "sender", "packet_sent", {
                "seq": self.current_seq,
                "bit": self.current_bit,
                "is_retry": False
            })
            print(event.to_json())
            
            # Send to server and wait for ACK with timeout
            ack_event = self.env.event()
            yield self.env.process(self.server_receiver.receive(packet, ack_event))
            
            # Wait for ACK or timeout
            try:
                yield self.env.timeout(self.timeout_duration)
                # Timeout occurred
                logger.info(f"Timeout occurred for packet {self.current_seq}")
                event = Event(self.env.now, "sender", "timeout", {
                    "seq": self.current_seq
                })
                print(event.to_json())
                
                # Retransmit
                logger.info(f"Retransmitting packet {self.current_seq}")
                event = Event(self.env.now, "sender", "packet_sent", {
                    "seq": self.current_seq,
                    "bit": self.current_bit,
                    "is_retry": True
                })
                print(event.to_json())
                
                # Retransmit packet
                ack_event = self.env.event()
                yield self.env.process(self.server_receiver.receive(packet, ack_event))
                yield ack_event  # Wait for ACK
            except simpy.Timeout:
                # ACK received in time
                pass
            
            # Process ACK
            logger.info(f"Sender received ACK for packet {self.current_seq}")
            event = Event(self.env.now, "sender", "ack_received", {
                "bit": self.current_bit
            })
            print(event.to_json())
            
            # Update state
            self.current_bit = 1 - self.current_bit  # Flip bit
            self.current_seq += 1
            self.packets_remaining -= 1
            
            if self.packets_remaining <= 0:
                self.is_busy = False
                logger.info("Sender finished uploading all packets")
                break


class ServerReceiver:
    """Server receiver that processes incoming packets from sender."""
    def __init__(self, env: simpy.Environment, name: str, server_sender):
        self.env = env
        self.name = name
        self.server_sender = server_sender
        self.expected_bit = 0
        self.storage_queue: deque = deque()
        self.processing_delay = 3000.0  # 3 seconds

    def receive(self, packet: Packet, ack_event):
        """Receive packet from sender."""
        logger.info(f"Server receiver received packet {packet.seq} with bit {packet.bit}")
        event = Event(self.env.now, "server_receiver", "packet_received", {
            "seq": packet.seq,
            "bit": packet.bit
        })
        print(event.to_json())
        
        # Process with delay
        yield self.env.timeout(self.processing_delay)
        
        # Check if packet is valid
        if packet.bit == self.expected_bit:
            # Valid packet
            logger.info(f"Server receiver accepted packet {packet.seq}")
            self.storage_queue.append(packet)
            self.expected_bit = 1 - self.expected_bit  # Flip expected bit
            
            # Send ACK immediately
            event = Event(self.env.now, "server_receiver", "ack_sent_to_sender", {
                "bit": packet.bit
            })
            print(event.to_json())
            
            # Forward to server sender
            self.env.process(self.server_sender.forward_packet(packet))
            
            # Signal ACK received
            ack_event.succeed()
        else:
            # Duplicate packet - resend ACK
            logger.info(f"Server receiver received duplicate packet {packet.seq}")
            event = Event(self.env.now, "server_receiver", "ack_sent_to_sender", {
                "bit": 1 - packet.bit  # Send previous bit ACK
            })
            print(event.to_json())
            
            # Signal ACK received
            ack_event.succeed()


class ServerSender:
    """Server sender that forwards packets to receiver."""
    def __init__(self, env: simpy.Environment, name: str, receiver, server_receiver):
        self.env = env
        self.name = name
        self.receiver = receiver
        self.server_receiver = server_receiver
        self.download_allowed = False
        self.is_sending = False
        self.current_bit = 0
        self.timeout_duration = 20000.0  # 20 seconds

    def download_valve_change(self, allowed: bool):
        """Handle download valve change."""
        self.download_allowed = allowed
        logger.info(f"Server sender download valve changed to {allowed}")
        event = Event(self.env.now, "server_sender", "download_valve_change", {
            "allowed": allowed
        })
        print(event.to_json())
        
        # Start sending if allowed and there are packets
        if allowed and self.server_receiver.storage_queue:
            self.env.process(self.forward_loop())

    def forward_packet(self, packet: Packet):
        """Forward packet to receiver."""
        if not self.download_allowed:
            return
            
        self.is_sending = True
        logger.info(f"Server sender forwarding packet {packet.seq} with bit {packet.bit}")
        event = Event(self.env.now, "server_sender", "packet_forwarded", {
            "seq": packet.seq,
            "bit": packet.bit
        })
        print(event.to_json())
        
        # Send to receiver and wait for ACK with timeout
        ack_event = self.env.event()
        yield self.env.process(self.receiver.receive_from_server(packet, ack_event))
        
        # Wait for ACK or timeout
        try:
            yield self.env.timeout(self.timeout_duration)
            # Timeout occurred
            logger.info(f"Timeout occurred for packet forwarding of packet {packet.seq}")
            event = Event(self.env.now, "server_sender", "timeout", {
                "seq": packet.seq
            })
            print(event.to_json())
            
            # Retransmit
            logger.info(f"Retransmitting packet {packet.seq} to receiver")
            ack_event = self.env.event()
            yield self.env.process(self.receiver.receive_from_server(packet, ack_event))
            yield ack_event  # Wait for ACK
        except simpy.Timeout:
            # ACK received in time
            pass
        
        # Process ACK
        logger.info(f"Server sender received ACK for forwarded packet {packet.seq}")
        event = Event(self.env.now, "server_sender", "ack_received_from_receiver", {
            "bit": packet.bit
        })
        print(event.to_json())
        
        self.is_sending = False

    def forward_loop(self):
        """Main forward loop for server sender."""
        while self.download_allowed and self.server_receiver.storage_queue:
            packet = self.server_receiver.storage_queue.popleft()
            yield self.env.process(self.forward_packet(packet))


class Receiver:
    """Receiver entity that downloads packets from server."""
    def __init__(self, env: simpy.Environment, name: str):
        self.env = env
        self.name = name
        self.processing_delay = 10000.0  # 10 seconds

    def receive_from_server(self, packet: Packet, ack_event):
        """Receive packet from server."""
        logger.info(f"Receiver received packet {packet.seq} with bit {packet.bit}")
        event = Event(self.env.now, "receiver", "processing_started", {
            "seq": packet.seq,
            "duration": self.processing_delay
        })
        print(event.to_json())
        
        # Process with delay
        yield self.env.timeout(self.processing_delay)
        
        # Send ACK
        logger.info(f"Receiver sending ACK for packet {packet.seq}")
        event = Event(self.env.now, "receiver", "ack_sent", {
            "bit": packet.bit
        })
        print(event.to_json())
        
        # Signal ACK received
        ack_event.succeed()


class Simulation:
    """Main simulation class."""
    def __init__(self, simulation_time: float = 10000000.0):
        self.env = simpy.Environment()
        self.simulation_time = simulation_time
        
        # Create entities
        self.server_sender = ServerSender(self.env, "server_sender", None, None)
        self.server_receiver = ServerReceiver(self.env, "server_receiver", self.server_sender)
        self.server_sender.receiver = None  # Will be set later
        self.server_sender.server_receiver = self.server_receiver
        
        self.sender = Sender(self.env, "sender", self.server_receiver)
        self.receiver = Receiver(self.env, "receiver")
        
        # Set up connections
        self.server_sender.receiver = self.receiver
        self.server_sender.server_receiver = self.server_receiver
        
        # Create subnets
        self.subnet_a1 = Subnet(self.env, "subnet_a1")  # Sender -> Server
        self.subnet_a2 = Subnet(self.env, "subnet_a2")  # Server -> Sender
        self.subnet_b1 = Subnet(self.env, "subnet_b1")  # Server -> Receiver
        self.subnet_b2 = Subnet(self.env, "subnet_b2")  # Receiver -> Server
        
        # Set up event handlers
        self.env.process(self.handle_input())
        
    def handle_input(self):
        """Handle input from stdin."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
                
            try:
                # Parse line: HH:MM:SS:mmm type value
                parts = line.split()
                if len(parts) < 3:
                    continue
                    
                timestamp_str = parts[0]
                event_type = parts[1]
                value = parts[2]
                
                # Convert timestamp to milliseconds
                time_parts = timestamp_str.split(':')
                if len(time_parts) == 4:
                    hours, minutes, seconds, milliseconds = map(int, time_parts)
                else:
                    hours, minutes, seconds = map(int, time_parts)
                    milliseconds = 0
                    
                timestamp_ms = (hours * 3600000 + minutes * 60000 + seconds * 1000 + milliseconds)
                
                # Process event
                if event_type == "control":
                    self.env.process(self.sender.control_cmd(int(value)))
                elif event_type == "request":
                    self.env.process(self.server_sender.download_valve_change(bool(int(value))))
                    
            except Exception as e:
                logger.error(f"Error processing input line: {line} - {e}")
                
    def run(self):
        """Run the simulation."""
        logger.info("Starting simulation...")
        self.env.run(until=self.simulation_time)
        logger.info("Simulation finished.")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Dropbox-like synchronization simulation')
    parser.add_argument('--simulation_time', type=float, default=10000000.0,
                       help='Simulation duration in milliseconds (default: 10000000.0)')
    
    args = parser.parse_args()
    
    # Create and run simulation
    sim = Simulation(args.simulation_time)
    sim.run()


if __name__ == "__main__":
    main()