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
        self.event_type = event_type
        self.val = val

    def to_json(self) -> str:
        return json.dumps({
            "timestamp_ms": self.timestamp_ms,
            "model": self.model,
            "type": self.event_type,
            "val": self.val
        })


class Packet:
    """Represents a data packet in the ABP protocol."""
    def __init__(self, seq: int, bit: int):
        self.seq = seq
        self.bit = bit


class Subnet:
    """Simulates a network subnet with fixed delay."""
    def __init__(self, env: simpy.Environment, delay: float):
        self.env = env
        self.delay = delay

    def send(self, packet: Packet, target):
        """Send packet with delay."""
        def send_process():
            yield self.env.timeout(self.delay)
            target.receive(packet)
        self.env.process(send_process())


class Sender:
    """Sender entity that uploads packets to the server."""
    def __init__(self, env: simpy.Environment, subnet_a1: Subnet, server_receiver):
        self.env = env
        self.subnet_a1 = subnet_a1
        self.server_receiver = server_receiver
        self.packets_remaining = 0
        self.total_packets_to_send = 0
        self.current_bit = 0
        self.current_seq = 1
        self.is_idle = True
        self.timeout_duration = 20.0  # seconds
        self.preparation_duration = 10.0  # seconds

    def control_cmd(self, added: int):
        """Handle control command to add packets to upload queue."""
        self.total_packets_to_send += added
        self.packets_remaining = self.total_packets_to_send
        logger.info(f"Control command: added {added} packets, total remaining: {self.packets_remaining}")
        
        # Emit event
        event = Event(
            timestamp_ms=self.env.now * 1000,
            model="sender",
            event_type="control_cmd",
            val={"added": added, "total_remaining": self.packets_remaining}
        )
        print(event.to_json(), file=sys.stderr)
        
        # If idle, start sending
        if self.is_idle:
            self.is_idle = False
            self.env.process(self.upload_loop())

    def upload_loop(self):
        """Main upload loop."""
        while self.packets_remaining > 0:
            # Preparation phase
            logger.info(f"Sender preparing to send packet {self.current_seq}")
            
            event = Event(
                timestamp_ms=self.env.now * 1000,
                model="sender",
                event_type="preparation_started",
                val={"duration": self.preparation_duration * 1000}
            )
            print(event.to_json(), file=sys.stderr)
            
            yield self.env.timeout(self.preparation_duration)
            
            # Send packet
            packet = Packet(self.current_seq, self.current_bit)
            logger.info(f"Sender sending packet {self.current_seq} with bit {self.current_bit}")
            
            event = Event(
                timestamp_ms=self.env.now * 1000,
                model="sender",
                event_type="packet_sent",
                val={"seq": self.current_seq, "bit": self.current_bit, "is_retry": False}
            )
            print(event.to_json(), file=sys.stderr)
            
            # Send to subnet
            self.subnet_a1.send(packet, self.server_receiver)
            
            # Simulate waiting for ACK with timeout
            yield self.env.timeout(self.timeout_duration)
            
            # Simulate successful ACK reception
            logger.info(f"Sender received ACK for packet {self.current_seq}")
            
            event = Event(
                timestamp_ms=self.env.now * 1000,
                model="sender",
                event_type="ack_received",
                val={"bit": self.current_bit}
            )
            print(event.to_json(), file=sys.stderr)
            
            # Update state
            self.current_bit = 1 - self.current_bit  # Flip bit
            self.current_seq += 1
            self.packets_remaining -= 1
            
            # If done, go idle
            if self.packets_remaining <= 0:
                self.is_idle = True
                logger.info("Sender is now idle")
                break


class ServerReceiver:
    """Server receiver that processes incoming packets."""
    def __init__(self, env: simpy.Environment, subnet_a2: Subnet, server_sender):
        self.env = env
        self.subnet_a2 = subnet_a2
        self.server_sender = server_sender
        self.expected_bit = 0
        self.storage_queue: deque = deque()
        self.processing_delay = 3.0  # seconds

    def receive(self, packet: Packet):
        """Receive packet from sender."""
        logger.info(f"Server receiver received packet {packet.seq} with bit {packet.bit}")
        
        event = Event(
            timestamp_ms=self.env.now * 1000,
            model="server_receiver",
            event_type="packet_received",
            val={"seq": packet.seq, "bit": packet.bit}
        )
        print(event.to_json(), file=sys.stderr)
        
        # Process with delay
        yield self.env.timeout(self.processing_delay)
        
        # Check if packet is valid
        if packet.bit == self.expected_bit:
            # Valid packet
            logger.info(f"Server receiver accepted packet {packet.seq}")
            
            # Send ACK back immediately
            ack_packet = Packet(packet.seq, packet.bit)
            logger.info(f"Server receiver sending ACK for packet {packet.seq}")
            
            event = Event(
                timestamp_ms=self.env.now * 1000,
                model="server_receiver",
                event_type="ack_sent_to_sender",
                val={"bit": packet.bit}
            )
            print(event.to_json(), file=sys.stderr)
            
            # Send ACK to sender
            self.subnet_a2.send(ack_packet, self.server_sender)
            
            # Store packet
            self.storage_queue.append(packet)
            logger.info(f"Server receiver stored packet {packet.seq}")
            
            # Flip expected bit
            self.expected_bit = 1 - self.expected_bit
        else:
            # Duplicate packet - resend ACK
            logger.info(f"Server receiver received duplicate packet {packet.seq}, resending ACK")
            
            event = Event(
                timestamp_ms=self.env.now * 1000,
                model="server_receiver",
                event_type="ack_sent_to_sender",
                val={"bit": self.expected_bit}
            )
            print(event.to_json(), file=sys.stderr)
            
            # Send ACK for previous bit
            ack_packet = Packet(packet.seq, self.expected_bit)
            self.subnet_a2.send(ack_packet, self.server_sender)


class ServerSender:
    """Server sender that forwards packets to receiver."""
    def __init__(self, env: simpy.Environment, subnet_b1: Subnet, receiver, subnet_b2: Subnet):
        self.env = env
        self.subnet_b1 = subnet_b1
        self.receiver = receiver
        self.subnet_b2 = subnet_b2
        self.storage_queue: deque = deque()
        self.download_allowed = False
        self.is_sending = False
        self.processing_delay = 0.0  # No processing delay
        self.timeout_duration = 20.0  # seconds

    def download_valve_change(self, allowed: bool):
        """Handle download valve change."""
        self.download_allowed = allowed
        logger.info(f"Download valve changed to {'allowed' if allowed else 'denied'}")
        
        event = Event(
            timestamp_ms=self.env.now * 1000,
            model="server_sender",
            event_type="download_valve_change",
            val={"allowed": allowed}
        )
        print(event.to_json(), file=sys.stderr)
        
        # If download is now allowed and we have packets, start sending
        if allowed and self.storage_queue:
            self.env.process(self.forward_loop())

    def store_packet(self, packet: Packet):
        """Store packet in queue."""
        self.storage_queue.append(packet)
        logger.info(f"Server sender stored packet {packet.seq}")
        
        # If download is allowed, start forwarding
        if self.download_allowed:
            self.env.process(self.forward_loop())

    def forward_loop(self):
        """Forward packets to receiver."""
        if self.is_sending:
            return  # Already sending
        
        self.is_sending = True
        logger.info("Server sender started forwarding packets")
        
        while self.storage_queue and self.download_allowed:
            # Get packet from queue
            packet = self.storage_queue.popleft()
            logger.info(f"Server sender forwarding packet {packet.seq}")
            
            event = Event(
                timestamp_ms=self.env.now * 1000,
                model="server_sender",
                event_type="packet_forwarded",
                val={"seq": packet.seq, "bit": packet.bit}
            )
            print(event.to_json(), file=sys.stderr)
            
            # Send to receiver
            self.subnet_b1.send(packet, self.receiver)
            
            # Wait for ACK with timeout
            yield self.env.timeout(self.timeout_duration)
            
            # Simulate successful ACK reception
            logger.info(f"Server sender received ACK for packet {packet.seq}")
            
            event = Event(
                timestamp_ms=self.env.now * 1000,
                model="server_sender",
                event_type="ack_received_from_receiver",
                val={"bit": packet.bit}
            )
            print(event.to_json(), file=sys.stderr)
            
            # If download is now denied, stop sending
            if not self.download_allowed:
                logger.info("Download denied during transfer, stopping")
                break
        
        self.is_sending = False


class Receiver:
    """Receiver entity that downloads packets from server."""
    def __init__(self, env: simpy.Environment, subnet_b2: Subnet, server_sender):
        self.env = env
        self.subnet_b2 = subnet_b2
        self.server_sender = server_sender
        self.processing_delay = 10.0  # seconds

    def receive(self, packet: Packet):
        """Receive packet from server."""
        logger.info(f"Receiver received packet {packet.seq}")
        
        event = Event(
            timestamp_ms=self.env.now * 1000,
            model="receiver",
            event_type="processing_started",
            val={"seq": packet.seq, "duration": self.processing_delay * 1000}
        )
        print(event.to_json(), file=sys.stderr)
        
        # Process with delay
        yield self.env.timeout(self.processing_delay)
        
        # Send ACK back
        logger.info(f"Receiver sending ACK for packet {packet.seq}")
        
        event = Event(
            timestamp_ms=self.env.now * 1000,
            model="receiver",
            event_type="ack_sent",
            val={"bit": packet.bit}
        )
        print(event.to_json(), file=sys.stderr)
        
        # Send ACK to server
        ack_packet = Packet(packet.seq, packet.bit)
        self.subnet_b2.send(ack_packet, self.server_sender)


def parse_time(time_str: str) -> float:
    """Parse time string in format HH:MM:SS:mmm to seconds."""
    h, m, s, ms = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s + ms / 1000.0


def main():
    parser = argparse.ArgumentParser(description='Dropbox-like synchronization simulation')
    parser.add_argument('--simulation_time', type=float, default=10000.0, 
                       help='Simulation duration in milliseconds (default: 10000.0)')
    
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create subnets
    subnet_a1 = Subnet(env, 3.0)  # Sender -> Server
    subnet_a2 = Subnet(env, 3.0)  # Server -> Sender
    subnet_b1 = Subnet(env, 3.0)  # Server -> Receiver
    subnet_b2 = Subnet(env, 3.0)  # Receiver -> Server
    
    # Create entities
    server_receiver = ServerReceiver(env, subnet_a2, None)  # Will be set later
    server_sender = ServerSender(env, subnet_b1, None, subnet_b2)  # Will be set later
    receiver = Receiver(env, subnet_b2, server_sender)
    sender = Sender(env, subnet_a1, server_receiver)
    
    # Set up connections
    server_receiver.server_sender = server_sender
    server_sender.receiver = receiver
    
    # Process input
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
            
        try:
            time_str, event_type, value = line.split(' ', 2)
            timestamp = parse_time(time_str)
            
            # Schedule the event
            if event_type == "control":
                value = int(value)
                def schedule_control():
                    yield env.timeout(timestamp - env.now)
                    sender.control_cmd(value)
                env.process(schedule_control())
            elif event_type == "request":
                value = int(value)
                def schedule_request():
                    yield env.timeout(timestamp - env.now)
                    server_sender.download_valve_change(bool(value))
                env.process(schedule_request())
        except Exception as e:
            logger.error(f"Error parsing input line '{line}': {e}")
    
    # Run simulation
    logger.info(f"Starting simulation for {args.simulation_time} ms")
    env.run(until=args.simulation_time / 1000.0)
    logger.info("Simulation completed")


if __name__ == "__main__":
    main()