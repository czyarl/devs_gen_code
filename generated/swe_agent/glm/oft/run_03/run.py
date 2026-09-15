#!/usr/bin/env python3
"""
Dropbox-like synchronization flow using two independent Alternating Bit Protocol (ABP) loops.
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
        self.in_transit = []
    
    def send(self, packet, source, destination):
        """Send a packet through the subnet with fixed delay."""
        logger.info(f"[{self.env.now:.0f}ms] {self.name}: {packet} from {source} to {destination}")
        self.env.process(self._transmit(packet, source, destination))
    
    def _transmit(self, packet, source, destination):
        """Simulate transmission delay."""
        yield self.env.timeout(self.delay_ms)
        self.output_callback(packet, source, destination)


class Sender:
    """Uploads packets to the server using ABP."""
    def __init__(self, env, subnet_a1, subnet_a2, event_callback):
        self.env = env
        self.subnet_a1 = subnet_a1
        self.subnet_a2 = subnet_a2
        self.event_callback = event_callback
        
        self.total_packets_to_send = 0
        self.packets_remaining = 0
        self.seq = 1
        self.bit = 0
        self.is_idle = True
        self.is_preparing = False
        self.waiting_for_ack = False
        self.current_packet = None
        self.timeout_process = None
        self.ack_timeout_ms = 20000
        self.preparation_time_ms = 10000
    
    def handle_control(self, added):
        """Handle control command to add packets to upload queue."""
        self.total_packets_to_send += added
        self.packets_remaining += added
        
        self.event_callback({
            "timestamp_ms": self.env.now,
            "model": "sender",
            "type": "control_cmd",
            "val": {"added": added, "total_remaining": self.packets_remaining}
        })
        
        logger.info(f"[{self.env.now:.0f}ms] Sender: control {added}, total remaining: {self.packets_remaining}")
        
        if self.is_idle and self.packets_remaining > 0:
            self.is_idle = False
            self._send_next_packet()
    
    def _send_next_packet(self):
        """Prepare and send the next packet."""
        if self.packets_remaining <= 0:
            self.is_idle = True
            return
        
        # Start preparation
        self.is_preparing = True
        self.event_callback({
            "timestamp_ms": self.env.now,
            "model": "sender",
            "type": "preparation_started",
            "val": {"duration": self.preparation_time_ms}
        })
        logger.info(f"[{self.env.now:.0f}ms] Sender: preparation started (10s)")
        
        self.env.process(self._prepare_and_send())
    
    def _prepare_and_send(self):
        """Prepare and send packet with delay."""
        yield self.env.timeout(self.preparation_time_ms)
        
        self.is_preparing = False
        self._transmit_packet()
    
    def _transmit_packet(self):
        """Transmit the current packet and wait for ACK."""
        self.current_packet = Packet(self.seq, self.bit)
        self.waiting_for_ack = True
        
        is_retry = False
        self.event_callback({
            "timestamp_ms": self.env.now,
            "model": "sender",
            "type": "packet_sent",
            "val": {"seq": self.seq, "bit": self.bit, "is_retry": is_retry}
        })
        logger.info(f"[{self.env.now:.0f}ms] Sender: packet_sent seq={self.seq}, bit={self.bit}, is_retry={is_retry}")
        
        # Send through subnet
        self.subnet_a1.send(self.current_packet, "sender", "server_receiver")
        
        # Start timeout timer
        self.timeout_process = self.env.process(self._wait_for_ack())
    
    def _wait_for_ack(self):
        """Wait for ACK with timeout."""
        try:
            yield self.env.timeout(self.ack_timeout_ms)
            # Timeout occurred
            self.event_callback({
                "timestamp_ms": self.env.now,
                "model": "sender",
                "type": "timeout",
                "val": {"seq": self.seq}
            })
            logger.info(f"[{self.env.now:.0f}ms] Sender: timeout for seq={self.seq}")
            
            # Retransmit
            self.event_callback({
                "timestamp_ms": self.env.now,
                "model": "sender",
                "type": "packet_sent",
                "val": {"seq": self.seq, "bit": self.bit, "is_retry": True}
            })
            logger.info(f"[{self.env.now:.0f}ms] Sender: retransmit seq={self.seq}, bit={self.bit}, is_retry=True")
            
            self.subnet_a1.send(self.current_packet, "sender", "server_receiver")
            self.timeout_process = self.env.process(self._wait_for_ack())
        except simpy.Interrupt:
            # ACK received
            pass
    
    def handle_ack(self, bit):
        """Handle ACK from server."""
        if not self.waiting_for_ack:
            return
        
        if bit == self.bit:
            # Correct ACK received
            if self.timeout_process and not self.timeout_process.triggered:
                self.timeout_process.interrupt()
            
            self.event_callback({
                "timestamp_ms": self.env.now,
                "model": "sender",
                "type": "ack_received",
                "val": {"bit": bit}
            })
            logger.info(f"[{self.env.now:.0f}ms] Sender: ack_received bit={bit}")
            
            # Update state
            self.packets_remaining -= 1
            self.seq += 1
            self.bit = 1 - self.bit
            self.waiting_for_ack = False
            self.current_packet = None
            
            # Send next packet if any remaining
            if self.packets_remaining > 0:
                self._send_next_packet()
            else:
                self.is_idle = True
                logger.info(f"[{self.env.now:.0f}ms] Sender: idle, all packets sent")
        else:
            # Wrong ACK bit, ignore (shouldn't happen in ABP)
            logger.warning(f"[{self.env.now:.0f}ms] Sender: received wrong ACK bit {bit}, expected {self.bit}")


class ServerReceiver:
    """Receives data from sender, processes, and sends ACK."""
    def __init__(self, env, subnet_a2, storage_queue, event_callback):
        self.env = env
        self.subnet_a2 = subnet_a2
        self.storage_queue = storage_queue
        self.event_callback = event_callback
        
        self.expected_bit = 0
        self.processing_time_ms = 3000
    
    def handle_packet(self, packet):
        """Handle incoming packet from sender."""
        self.event_callback({
            "timestamp_ms": self.env.now,
            "model": "server_receiver",
            "type": "packet_received",
            "val": {"seq": packet.seq, "bit": packet.bit}
        })
        logger.info(f"[{self.env.now:.0f}ms] ServerReceiver: packet_received seq={packet.seq}, bit={packet.bit}")
        
        self.env.process(self._process_packet(packet))
    
    def _process_packet(self, packet):
        """Process packet with delay."""
        yield self.env.timeout(self.processing_time_ms)
        
        if packet.bit == self.expected_bit:
            # New packet
            self.storage_queue.append(packet)
            logger.info(f"[{self.env.now:.0f}ms] ServerReceiver: stored packet seq={packet.seq} in queue")
            
            # Send ACK
            self.subnet_a2.send(Packet(0, packet.bit), "server_receiver", "sender")
            self.event_callback({
                "timestamp_ms": self.env.now,
                "model": "server_receiver",
                "type": "ack_sent_to_sender",
                "val": {"bit": packet.bit}
            })
            logger.info(f"[{self.env.now:.0f}ms] ServerReceiver: ack_sent_to_sender bit={packet.bit}")
            
            # Flip expected bit
            self.expected_bit = 1 - self.expected_bit
        else:
            # Duplicate packet, resend previous ACK
            self.subnet_a2.send(Packet(0, 1 - self.expected_bit), "server_receiver", "sender")
            self.event_callback({
                "timestamp_ms": self.env.now,
                "model": "server_receiver",
                "type": "ack_sent_to_sender",
                "val": {"bit": 1 - self.expected_bit}
            })
            logger.info(f"[{self.env.now:.0f}ms] ServerReceiver: duplicate packet, resending ACK bit={1 - self.expected_bit}")


class ServerSender:
    """Sends data from storage queue to receiver using ABP."""
    def __init__(self, env, subnet_b1, subnet_b2, storage_queue, event_callback):
        self.env = env
        self.subnet_b1 = subnet_b1
        self.subnet_b2 = subnet_b2
        self.storage_queue = storage_queue
        self.event_callback = event_callback
        
        self.download_allowed = False
        self.seq = 1
        self.bit = 0
        self.waiting_for_ack = False
        self.current_packet = None
        self.timeout_process = None
        self.ack_timeout_ms = 20000
    
    def handle_request(self, allowed):
        """Handle request command to toggle download permission."""
        self.download_allowed = allowed
        self.event_callback({
            "timestamp_ms": self.env.now,
            "model": "server_sender",
            "type": "download_valve_change",
            "val": {"allowed": allowed}
        })
        logger.info(f"[{self.env.now:.0f}ms] ServerSender: download_valve_change allowed={allowed}")
        
        # Try to send if allowed and not waiting
        if self.download_allowed and not self.waiting_for_ack and self.storage_queue:
            self._send_next_packet()
    
    def _send_next_packet(self):
        """Send next packet from storage queue."""
        if not self.storage_queue or not self.download_allowed or self.waiting_for_ack:
            return
        
        packet = self.storage_queue.popleft()
        self.current_packet = packet
        self.waiting_for_ack = True
        
        self.event_callback({
            "timestamp_ms": self.env.now,
            "model": "server_sender",
            "type": "packet_forwarded",
            "val": {"seq": packet.seq, "bit": packet.bit}
        })
        logger.info(f"[{self.env.now:.0f}ms] ServerSender: packet_forwarded seq={packet.seq}, bit={packet.bit}")
        
        # Send through subnet
        self.subnet_b1.send(packet, "server_sender", "receiver")
        
        # Start timeout timer
        self.timeout_process = self.env.process(self._wait_for_ack())
    
    def _wait_for_ack(self):
        """Wait for ACK with timeout."""
        try:
            yield self.env.timeout(self.ack_timeout_ms)
            # Timeout occurred - retransmit
            logger.info(f"[{self.env.now:.0f}ms] ServerSender: timeout for seq={self.current_packet.seq}")
            self.subnet_b1.send(self.current_packet, "server_sender", "receiver")
            self.timeout_process = self.env.process(self._wait_for_ack())
        except simpy.Interrupt:
            # ACK received
            pass
    
    def handle_ack(self, bit):
        """Handle ACK from receiver."""
        if not self.waiting_for_ack:
            return
        
        if bit == self.bit:
            # Correct ACK received
            if self.timeout_process and not self.timeout_process.triggered:
                self.timeout_process.interrupt()
            
            self.event_callback({
                "timestamp_ms": self.env.now,
                "model": "server_sender",
                "type": "ack_received_from_receiver",
                "val": {"bit": bit}
            })
            logger.info(f"[{self.env.now:.0f}ms] ServerSender: ack_received_from_receiver bit={bit}")
            
            # Update state
            self.seq += 1
            self.bit = 1 - self.bit
            self.waiting_for_ack = False
            self.current_packet = None
            
            # Try to send next packet if allowed
            if self.download_allowed and self.storage_queue:
                self._send_next_packet()


class Receiver:
    """Receives data from server, processes, and sends ACK."""
    def __init__(self, env, subnet_b2, event_callback):
        self.env = env
        self.subnet_b2 = subnet_b2
        self.event_callback = event_callback
        
        self.expected_bit = 0
        self.processing_time_ms = 10000
    
    def handle_packet(self, packet):
        """Handle incoming packet from server."""
        self.env.process(self._process_packet(packet))
    
    def _process_packet(self, packet):
        """Process packet with delay."""
        self.event_callback({
            "timestamp_ms": self.env.now,
            "model": "receiver",
            "type": "processing_started",
            "val": {"seq": packet.seq, "duration": self.processing_time_ms}
        })
        logger.info(f"[{self.env.now:.0f}ms] Receiver: processing_started seq={packet.seq}, duration=10000")
        
        yield self.env.timeout(self.processing_time_ms)
        
        # Send ACK
        self.subnet_b2.send(Packet(0, packet.bit), "receiver", "server_sender")
        self.event_callback({
            "timestamp_ms": self.env.now,
            "model": "receiver",
            "type": "ack_sent",
            "val": {"bit": packet.bit}
        })
        logger.info(f"[{self.env.now:.0f}ms] Receiver: ack_sent bit={packet.bit}")


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


def parse_stdin():
    """Parse stdin commands and return list of (time_ms, type, value)."""
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
            commands.append((time_ms, cmd_type, int(value)))
        elif cmd_type == "request":
            commands.append((time_ms, cmd_type, int(value)))
        else:
            logger.warning(f"Unknown command type: {cmd_type}")
    return sorted(commands, key=lambda x: x[0])


def main():
    parser = argparse.ArgumentParser(description="Dropbox-like synchronization simulation")
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=10000000.0,
        help="Simulation duration in milliseconds (default: 10000000.0)"
    )
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Storage queue (shared between ServerReceiver and ServerSender)
    storage_queue = deque()
    
    # Event list for output
    events = []
    
    def event_callback(event):
        """Callback to record events."""
        events.append(event)
    
    # Create subnets (3s delay = 3000ms)
    subnet_a1 = Subnet(env, "A1", 3000, lambda p, s, d: server_receiver.handle_packet(p))
    subnet_a2 = Subnet(env, "A2", 3000, lambda p, s, d: sender.handle_ack(p.bit))
    subnet_b1 = Subnet(env, "B1", 3000, lambda p, s, d: receiver.handle_packet(p))
    subnet_b2 = Subnet(env, "B2", 3000, lambda p, s, d: server_sender.handle_ack(p.bit))
    
    # Create components
    sender = Sender(env, subnet_a1, subnet_a2, event_callback)
    server_receiver = ServerReceiver(env, subnet_a2, storage_queue, event_callback)
    server_sender = ServerSender(env, subnet_b1, subnet_b2, storage_queue, event_callback)
    receiver = Receiver(env, subnet_b2, event_callback)
    
    # Parse stdin commands
    commands = parse_stdin()
    
    # Schedule commands
    for time_ms, cmd_type, value in commands:
        def command_generator(t=time_ms, c=cmd_type, v=value):
            yield env.timeout(t - env.now)
            if c == "control":
                sender.handle_control(v)
            elif c == "request":
                server_sender.handle_request(bool(v))
        env.process(command_generator())
    
    # Run simulation
    logger.info(f"Starting simulation for {args.simulation_time}ms")
    env.run(until=args.simulation_time)
    logger.info(f"Simulation completed at {env.now:.0f}ms")
    
    # Output events as JSONL
    for event in sorted(events, key=lambda e: e["timestamp_ms"]):
        print(json.dumps(event))


if __name__ == "__main__":
    main()