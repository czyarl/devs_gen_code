#!/usr/bin/env python3
"""
Dropbox-like synchronization simulation using Alternating Bit Protocol (ABP)
with two independent ABP loops:
- Loop 1 (Upload): Sender -> SubnetA -> Server
- Loop 2 (Download): Server -> SubnetB -> Receiver
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
    """Event class to represent simulation events"""
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
    """Packet class for data transmission"""
    def __init__(self, seq: int, bit: int, data: Optional[str] = None):
        self.seq = seq
        self.bit = bit
        self.data = data


class Subnet:
    """Reliable FIFO subnet with fixed delay"""
    def __init__(self, env: simpy.Environment, delay: float, name: str):
        self.env = env
        self.delay = delay
        self.name = name

    def send(self, packet: Packet, destination):
        """Send packet with delay"""
        yield self.env.timeout(self.delay)
        logger.info(f"Subnet {self.name} sending packet {packet.seq} to {type(destination).__name__}")
        destination.receive(packet)


class Sender:
    """Sender entity that uploads packets to the server"""
    def __init__(self, env: simpy.Environment, server_receiver, subnet_a1):
        self.env = env
        self.server_receiver = server_receiver
        self.subnet_a1 = subnet_a1
        self.packets_remaining = 0
        self.total_packets_to_send = 0
        self.current_bit = 0
        self.current_seq = 1
        self.is_idle = True
        self.waiting_for_ack = False
        self.retry_count = 0
        self.max_retries = 3
        self.ack_event = None  # Event to signal ACK receipt

    def control_cmd(self, added: int):
        """Handle control command to add packets to upload queue"""
        self.total_packets_to_send += added
        self.packets_remaining = self.total_packets_to_send
        logger.info(f"Control command: added {added} packets, total remaining: {self.packets_remaining}")
        
        # Emit event
        event = Event(
            timestamp_ms=self.env.now,
            model="sender",
            event_type="control_cmd",
            val={"added": added, "total_remaining": self.packets_remaining}
        )
        print(event.to_json())
        
        # Start sending if idle
        if self.is_idle:
            self.is_idle = False
            self.env.process(self.upload_loop())

    def upload_loop(self):
        """Main upload loop"""
        while self.packets_remaining > 0:
            # Preparation phase
            logger.info(f"Sender preparing to send packet {self.current_seq}")
            event = Event(
                timestamp_ms=self.env.now,
                model="sender",
                event_type="preparation_started",
                val={"duration": 10000}
            )
            print(event.to_json())
            
            yield self.env.timeout(10000)  # 10s preparation
            
            # Send packet
            packet = Packet(self.current_seq, self.current_bit)
            logger.info(f"Sender sending packet {self.current_seq} with bit {self.current_bit}")
            
            event = Event(
                timestamp_ms=self.env.now,
                model="sender",
                event_type="packet_sent",
                val={"seq": self.current_seq, "bit": self.current_bit, "is_retry": self.retry_count > 0}
            )
            print(event.to_json())
            
            # Create event to wait for ACK
            self.ack_event = self.env.event()
            self.waiting_for_ack = True
            
            # Send to subnet
            self.env.process(self.subnet_a1.send(packet, self.server_receiver))
            
            # Wait for ACK with timeout
            try:
                # Wait for either ACK or timeout
                yield self.env.timeout(20000) | self.ack_event  # 20s timeout
                if self.ack_event.triggered:
                    # ACK received
                    logger.info(f"Sender received ACK for packet {self.current_seq}")
                    event = Event(
                        timestamp_ms=self.env.now,
                        model="sender",
                        event_type="ack_received",
                        val={"bit": self.current_bit}
                    )
                    print(event.to_json())
                    
                    # Flip bit and increment sequence
                    self.current_bit = 1 - self.current_bit
                    self.current_seq += 1
                    self.packets_remaining -= 1
                    self.retry_count = 0
                    self.waiting_for_ack = False
                else:
                    # Timeout
                    logger.info(f"Sender timeout for packet {self.current_seq}")
                    event = Event(
                        timestamp_ms=self.env.now,
                        model="sender",
                        event_type="timeout",
                        val={"seq": self.current_seq}
                    )
                    print(event.to_json())
                    
                    self.retry_count += 1
                    if self.retry_count >= self.max_retries:
                        logger.error(f"Max retries exceeded for packet {self.current_seq}")
                        self.packets_remaining = 0
                        self.is_idle = True
                        break
                    else:
                        # Retry sending same packet
                        logger.info(f"Retrying packet {self.current_seq}")
                        self.waiting_for_ack = False
                        continue
            except Exception as e:
                logger.error(f"Error in upload loop: {e}")
                break

    def receive(self, packet: Packet):
        """Receive packet from subnet (ACK from server)"""
        logger.info(f"Sender received ACK packet {packet.seq} with bit {packet.bit}")
        self.receive_ack(packet.bit)

    def receive_ack(self, bit: int):
        """Receive ACK from server"""
        if self.waiting_for_ack:
            if bit == self.current_bit:
                # Correct ACK - trigger the event
                self.ack_event.succeed()
                self.waiting_for_ack = False
            else:
                # Duplicate or wrong ACK - ignore for now
                logger.warning(f"Received wrong ACK bit {bit}, expected {self.current_bit}")


class ServerReceiver:
    """Server receiver that processes incoming packets"""
    def __init__(self, env: simpy.Environment, sender, subnet_a2):
        self.env = env
        self.sender = sender
        self.subnet_a2 = subnet_a2
        self.expected_bit = 0
        self.storage_queue: Deque[Packet] = deque()
        self.processing_delay = 3000  # 3 seconds

    def receive(self, packet: Packet):
        """Receive packet from sender"""
        logger.info(f"Server receiver received packet {packet.seq} with bit {packet.bit}")
        
        event = Event(
            timestamp_ms=self.env.now,
            model="server_receiver",
            event_type="packet_received",
            val={"seq": packet.seq, "bit": packet.bit}
        )
        print(event.to_json())
        
        # Process with delay
        yield self.env.timeout(self.processing_delay)
        
        # Check if packet is correct
        if packet.bit == self.expected_bit:
            # Correct packet
            logger.info(f"Server receiver accepted packet {packet.seq}")
            
            # Send ACK back to sender
            ack_packet = Packet(packet.seq, packet.bit)
            logger.info(f"Server receiver sending ACK for packet {packet.seq} to {type(self.sender).__name__}")
            
            event = Event(
                timestamp_ms=self.env.now,
                model="server_receiver",
                event_type="ack_sent_to_sender",
                val={"bit": packet.bit}
            )
            print(event.to_json())
            
            # Send ACK to sender
            logger.info(f"About to send ACK via subnet_a2 to {type(self.sender).__name__}")
            self.env.process(self.subnet_a2.send(ack_packet, self.sender))
            
            # Store packet
            self.storage_queue.append(packet)
            logger.info(f"Packet {packet.seq} stored in queue, queue size: {len(self.storage_queue)}")
            
            # Flip expected bit
            self.expected_bit = 1 - self.expected_bit
        else:
            # Duplicate packet - resend ACK
            logger.info(f"Server receiver duplicate packet {packet.seq}, resending ACK")
            
            ack_packet = Packet(packet.seq, self.expected_bit)
            logger.info(f"Server receiver resending ACK for packet {packet.seq}")
            
            event = Event(
                timestamp_ms=self.env.now,
                model="server_receiver",
                event_type="ack_sent_to_sender",
                val={"bit": self.expected_bit}
            )
            print(event.to_json())
            
            # Send ACK to sender
            logger.info(f"About to send duplicate ACK via subnet_a2 to {type(self.sender).__name__}")
            self.env.process(self.subnet_a2.send(ack_packet, self.sender))


class ServerSender:
    """Server sender that forwards packets to receiver"""
    def __init__(self, env: simpy.Environment, receiver, subnet_b1, server_receiver):
        self.env = env
        self.receiver = receiver
        self.subnet_b1 = subnet_b1
        self.server_receiver = server_receiver
        self.download_allowed = False
        self.is_sending = False
        self.current_bit = 0
        self.current_seq = 1
        self.waiting_for_ack = False
        self.ack_event = None  # Event to signal ACK receipt

    def download_valve_change(self, allowed: bool):
        """Handle download valve change"""
        self.download_allowed = allowed
        logger.info(f"Download valve changed to {'allowed' if allowed else 'denied'}")
        
        event = Event(
            timestamp_ms=self.env.now,
            model="server_sender",
            event_type="download_valve_change",
            val={"allowed": allowed}
        )
        print(event.to_json())
        
        # Start sending if allowed and there are packets
        if allowed and len(self.server_receiver.storage_queue) > 0:
            self.env.process(self.forward_loop())

    def forward_loop(self):
        """Forward packets to receiver"""
        if self.is_sending:
            return  # Already sending
        
        self.is_sending = True
        while self.download_allowed and len(self.server_receiver.storage_queue) > 0:
            # Get packet from storage
            packet = self.server_receiver.storage_queue.popleft()
            logger.info(f"Server sender forwarding packet {packet.seq}")
            
            event = Event(
                timestamp_ms=self.env.now,
                model="server_sender",
                event_type="packet_forwarded",
                val={"seq": packet.seq, "bit": packet.bit}
            )
            print(event.to_json())
            
            # Create event to wait for ACK
            self.ack_event = self.env.event()
            self.waiting_for_ack = True
            
            # Send to receiver
            self.env.process(self.subnet_b1.send(packet, self.receiver))
            
            # Wait for ACK with timeout
            try:
                # Wait for either ACK or timeout
                yield self.env.timeout(20000) | self.ack_event  # 20s timeout
                if self.ack_event.triggered:
                    # ACK received
                    logger.info(f"Server sender received ACK for packet {packet.seq}")
                    event = Event(
                        timestamp_ms=self.env.now,
                        model="server_sender",
                        event_type="ack_received_from_receiver",
                        val={"bit": packet.bit}
                    )
                    print(event.to_json())
                    
                    # Flip bit and increment sequence
                    self.current_bit = 1 - self.current_bit
                    self.current_seq += 1
                    self.waiting_for_ack = False
                else:
                    # Timeout
                    logger.info(f"Server sender timeout for packet {packet.seq}")
                    # Retry logic would go here if needed
                    break
            except Exception as e:
                logger.error(f"Error in forward loop: {e}")
                break
        
        self.is_sending = False

    def receive_ack(self, bit: int):
        """Receive ACK from receiver"""
        if self.waiting_for_ack:
            # Trigger ACK received event
            if bit == self.current_bit:
                self.ack_event.succeed()
                self.waiting_for_ack = False
            else:
                logger.warning(f"Received wrong ACK bit {bit}, expected {self.current_bit}")


class Receiver:
    """Receiver entity that downloads packets from server"""
    def __init__(self, env: simpy.Environment, server_sender, subnet_b2):
        self.env = env
        self.server_sender = server_sender
        self.subnet_b2 = subnet_b2
        self.processing_delay = 10000  # 10 seconds

    def receive(self, packet: Packet):
        """Receive packet from server"""
        logger.info(f"Receiver received packet {packet.seq} with bit {packet.bit}")
        
        # Processing delay
        event = Event(
            timestamp_ms=self.env.now,
            model="receiver",
            event_type="processing_started",
            val={"seq": packet.seq, "duration": self.processing_delay}
        )
        print(event.to_json())
        
        yield self.env.timeout(self.processing_delay)
        
        # Send ACK back to server
        ack_packet = Packet(packet.seq, packet.bit)
        logger.info(f"Receiver sending ACK for packet {packet.seq}")
        
        event = Event(
            timestamp_ms=self.env.now,
            model="receiver",
            event_type="ack_sent",
            val={"bit": packet.bit}
        )
        print(event.to_json())
        
        # Send ACK to server
        self.env.process(self.subnet_b2.send(ack_packet, self.server_sender))


def parse_input_line(line: str):
    """Parse input line into timestamp, type, and value"""
    parts = line.strip().split()
    if len(parts) < 3:
        return None, None, None
    
    timestamp = parts[0]
    event_type = parts[1]
    value = parts[2]
    
    # Convert timestamp to milliseconds
    time_parts = timestamp.split(':')
    if len(time_parts) == 4:  # HH:MM:SS:mmm format
        hours, minutes, seconds, milliseconds = map(int, time_parts)
    else:  # HH:MM:SS format
        hours, minutes, seconds = map(int, time_parts)
        milliseconds = 0
    
    timestamp_ms = (hours * 3600 + minutes * 60 + seconds) * 1000 + milliseconds
    
    return timestamp_ms, event_type, value


def main():
    parser = argparse.ArgumentParser(description='Dropbox-like synchronization simulation')
    parser.add_argument('--simulation_time', type=float, default=10000000.0,
                       help='Simulation duration in milliseconds (default: 10000000.0)')
    
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create components
    subnet_a1 = Subnet(env, 3000, "SubnetA1")  # 3s delay
    subnet_a2 = Subnet(env, 3000, "SubnetA2")  # 3s delay
    subnet_b1 = Subnet(env, 3000, "SubnetB1")  # 3s delay
    subnet_b2 = Subnet(env, 3000, "SubnetB2")  # 3s delay
    
    # Create entities
    server_receiver = ServerReceiver(env, None, subnet_a2)  # Will be updated later
    server_sender = ServerSender(env, None, subnet_b1, server_receiver)  # Will be updated later
    receiver = Receiver(env, server_sender, subnet_b2)  # Will be updated later
    sender = Sender(env, server_receiver, subnet_a1)  # Will be updated later
    
    # Update references
    server_receiver.sender = sender
    server_sender.receiver = receiver
    sender.server_receiver = server_receiver
    server_sender.server_receiver = server_receiver
    receiver.server_sender = server_sender
    
    # Process input from stdin
    logger.info("Processing input events...")
    for line in sys.stdin:
        if not line.strip():
            continue
            
        timestamp_ms, event_type, value = parse_input_line(line)
        if timestamp_ms is None:
            continue
            
        logger.info(f"Scheduling {event_type} event at {timestamp_ms}ms")
        # Schedule the event
        if event_type == "control":
            env.process(delayed_control(env, sender, int(value), timestamp_ms))
        elif event_type == "request":
            env.process(delayed_request(env, server_sender, int(value), timestamp_ms))
    
    # Run simulation
    logger.info(f"Starting simulation for {args.simulation_time} ms")
    env.run(until=args.simulation_time)
    logger.info("Simulation completed")


def delayed_control(env, sender, value, timestamp_ms):
    """Delay control command until specified time"""
    yield env.timeout(timestamp_ms)
    sender.control_cmd(value)


def delayed_request(env, server_sender, value, timestamp_ms):
    """Delay request command until specified time"""
    yield env.timeout(timestamp_ms)
    server_sender.download_valve_change(bool(value))


if __name__ == "__main__":
    main()