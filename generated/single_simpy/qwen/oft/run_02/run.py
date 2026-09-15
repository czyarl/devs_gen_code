```python
import argparse
import sys
import json
import logging
import time
from collections import deque
from typing import Optional, List
import simpy

# Global simulation environment
env = simpy.Environment()

# Event types
EVENT_TYPES = {
    "control_cmd": "control",
    "download_valve_change": "request",
    "preparation_started": "preparation_started",
    "packet_sent": "packet_sent",
    "ack_received": "ack_received",
    "timeout": "timeout",
    "packet_received": "packet_received",
    "ack_sent_to_sender": "ack_sent_to_sender",
    "packet_forwarded": "packet_forwarded",
    "ack_received_from_receiver": "ack_received_from_receiver",
    "processing_started": "processing_started",
    "ack_sent": "ack_sent"
}

# Global simulation time in milliseconds
SIMULATION_TIME_MS = 10000000.0  # Default 10 seconds

# Global variables
sender_packets_remaining = 0
sender_preparing = False
server_receiver_expected_bit = 0
server_receiver_storage_queue = deque()
server_sender_download_allowed = False
server_sender_sending = False
server_sender_current_packet = None
receiver_processing = False
receiver_current_packet = None

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)

class Event:
    def __init__(self, timestamp_ms, model, event_type, val):
        self.timestamp_ms = timestamp_ms
        self.model = model
        self.type = event_type
        self.val = val

    def to_json(self):
        return json.dumps({
            "timestamp_ms": self.timestamp_ms,
            "model": self.model,
            "type": self.type,
            "val": self.val
        })

# Helper function to parse time strings
def parse_time(time_str):
    # Format: HH:MM:SS:mmm or HH:MM:SS
    parts = time_str.split(':')
    if len(parts) == 4:
        hours, minutes, seconds, milliseconds = map(int, parts)
    else:
        hours, minutes, seconds = map(int, parts)
        milliseconds = 0
    return (hours * 3600 + minutes * 60 + seconds) * 1000 + milliseconds

# Simulated network delay
def network_delay(delay_ms):
    return env.timeout(delay_ms / 1000.0)  # Convert to seconds for simpy

# Sender Entity
class Sender:
    def __init__(self):
        self.packets_remaining = 0
        self.seq = 1
        self.bit = 0
        self.preparing = False
        self.waiting_for_ack = False
        self.timeout_count = 0
        self.max_timeout = 3

    def control(self, added_packets):
        global sender_packets_remaining
        sender_packets_remaining += added_packets
        logging.info(f"Sender received control command: added {added_packets} packets, total remaining: {sender_packets_remaining}")
        if sender_packets_remaining > 0 and not self.preparing:
            self.start_preparation()

    def start_preparation(self):
        global sender_preparing
        if not self.preparing:
            self.preparing = True
            sender_preparing = True
            # Send preparation started event
            event = Event(env.now * 1000, "sender", "preparation_started", {"duration": 10000})
            print(event.to_json())
            logging.debug(f"Sender: Preparation started at {env.now}")
            # Wait 10 seconds (simulated)
            yield network_delay(10000)
            # Start sending packets
            self.send_packet()

    def send_packet(self):
        global sender_packets_remaining
        if sender_packets_remaining <= 0:
            return
        # Check if we're waiting for an ACK
        if self.waiting_for_ack:
            return
        self.waiting_for_ack = True
        # Send packet
        event = Event(env.now * 1000, "sender", "packet_sent", {"seq": self.seq, "bit": self.bit, "is_retry": self.timeout_count > 0})
        print(event.to_json())
        logging.debug(f"Sender: Sent packet seq={self.seq}, bit={self.bit}")
        # Simulate network delay (3s)
        yield network_delay(3000)
        # Simulate timeout logic
        # For simplicity, we'll assume ACK is received after some time
        # In a real implementation, we'd need to wait for ACK
        # For now, we'll assume it's received
        self.handle_ack()

    def handle_ack(self):
        global sender_packets_remaining
        # Simulate receiving ACK
        self.timeout_count = 0
        # Send ACK received event
        event = Event(env.now * 1000, "sender", "ack_received", {"bit": self.bit})
        print(event.to_json())
        logging.debug(f"Sender: Received ACK bit={self.bit}")
        # Update state
        self.seq += 1
        self.bit = 1 - self.bit  # Flip bit
        sender_packets_remaining -= 1
        self.waiting_for_ack = False
        if sender_packets_remaining > 0:
            # Send next packet
            self.send_packet()

    def handle_timeout(self):
        global sender_packets_remaining
        if self.timeout_count < self.max_timeout:
            self.timeout_count += 1
            event = Event(env.now * 1000, "sender", "timeout", {"seq": self.seq})
            print(event.to_json())
            logging.debug(f"Sender: Timeout for packet seq={self.seq}")
            # Retransmit packet
            self.send_packet()
        else:
            logging.warning("Sender: Max timeout reached")
            self.waiting_for_ack = False
            self.timeout_count = 0

# Server Receiver Entity
class ServerReceiver:
    def __init__(self):
        self.expected_bit = 0

    def handle_packet(self, packet_seq, packet_bit):
        event = Event(env.now * 1000, "server_receiver", "packet_received", {"seq": packet_seq, "bit": packet_bit})
        print(event.to_json())
        logging.debug(f"ServerReceiver: Received packet seq={packet_seq}, bit={packet_bit}")
        # Simulate 3s processing delay
        yield network_delay(3000)
        # Check if bit matches expected bit
        if packet_bit == self.expected_bit:
            # Send ACK
            event = Event(env.now * 1000, "server_receiver", "ack_sent_to_sender", {"bit": packet_bit})
            print(event.to_json())
            logging.debug(f"ServerReceiver: Sent ACK bit={packet_bit}")
            # Add to storage queue
            server_receiver_storage_queue.append((packet_seq, packet_bit))
            # Flip expected bit
            self.expected_bit = 1 - self.expected_bit
        else:
            # Duplicate packet - resend ACK
            event = Event(env.now * 1000, "server_receiver", "ack_sent_to_sender", {"bit": self.expected_bit})
            print(event.to_json())
            logging.debug(f"ServerReceiver: Resent ACK bit={self.expected_bit} (duplicate)")

# Server Sender Entity
class ServerSender:
    def __init__(self):
        self.sending = False
        self.current_packet = None
        self.waiting_for_ack = False

    def handle_request(self, allowed):
        global server_sender_download_allowed
        server_sender_download_allowed = allowed
        logging.info(f"ServerSender: Download allowed = {server_sender_download_allowed}")
        event = Event(env.now * 1000, "server_sender", "download_valve_change", {"allowed": allowed})
        print(event.to_json())
        if not allowed:
            # If download is disabled and we're currently sending, finish current packet
            if self.sending and self.current_packet:
                self.finish_current_transfer()
        else:
            # If download is enabled, try to send packets
            self.try_send_packets()

    def try_send_packets(self):
        global server_sender_download_allowed, server_receiver_storage_queue, server_sender_sending
        if not server_sender_download_allowed:
            return
        if not server_receiver_storage_queue:
            return
        if self.sending:
            return
        # Start sending
        self.sending = True
        self.send_next_packet()

    def send_next_packet(self):
        global server_receiver_storage_queue, server_sender_sending
        if not server_receiver_storage_queue:
            self.sending = False
            return
        packet = server_receiver_storage_queue.popleft()
        packet_seq, packet_bit = packet
        self.current_packet = packet
        self.waiting_for_ack = True
        # Send packet
        event = Event(env.now * 1000, "server_sender", "packet_forwarded", {"seq": packet_seq, "bit": packet_bit})
        print(event.to_json())
        logging.debug(f"ServerSender: Forwarded packet seq={packet_seq}, bit={packet_bit}")
        # Simulate network delay (3s)
        yield network_delay(3000)
        # Simulate receiving ACK from receiver
        self.handle_ack_from_receiver()

    def handle_ack_from_receiver(self):
        global server_sender_sending
        # Simulate receiving ACK
        self.waiting_for_ack = False
        # Send ACK received event
        event = Event(env.now * 1000, "server_sender", "ack_received_from_receiver", {"bit": self.current_packet[1]})
        print(event.to_json())
        logging.debug(f"ServerSender: Received ACK from receiver bit={self.current_packet[1]}")
        # If download is still allowed, continue sending
        if server_sender_download_allowed:
            self.send_next_packet()
        else:
            self.sending = False

    def finish_current_transfer(self):
        # Finish current transfer gracefully
        self.sending = False
        self.current_packet = None

# Receiver Entity
class Receiver:
    def __init__(self):
        self.processing = False
        self.current_packet = None

    def handle_packet(self, packet_seq, packet_bit):
        self.current_packet = (packet_seq, packet_bit)
        self.processing = True
        # Send processing started event
        event = Event(env.now * 1000, "receiver", "processing_started", {"seq": packet_seq, "duration": 10000})
        print(event.to_json())
        logging.debug(f"Receiver: Started processing packet seq={packet_seq}")
        # Simulate 10s processing delay
        yield network_delay(10000)
        # Send ACK
        event = Event(env.now * 1000, "receiver", "ack_sent", {"bit": packet_bit})
        print(event.to_json())
        logging.debug(f"Receiver: Sent ACK bit={packet_bit}")
        self.processing = False
        self.current_packet = None

# Main simulation
def run_simulation(simulation_time_ms):
    global SIMULATION_TIME_MS
    SIMULATION_TIME_MS = simulation_time_ms
    
    # Create entities
    sender = Sender()
    server_receiver = ServerReceiver()
    server_sender = ServerSender()
    receiver = Receiver()

    # Process input
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            parts = line.split(' ', 2)
            timestamp_str = parts[0]
            event_type = parts[1]
            value_str = parts[2]
            
            timestamp_ms = parse_time(timestamp_str)
            
            if event_type == "control":
                # This is a control command
                added_packets = int(value_str)
                # Schedule control command
                def control_command():
                    sender.control(added_packets)
                    # Start preparation if needed
                    if not sender.preparing and sender.packets_remaining > 0:
                        env.process(sender.start_preparation())
                
                # Schedule the event
                def delayed_control():
                    yield env.timeout(timestamp_ms / 1000.0)
                    control_command()
                
                env.process(delayed_control())
            elif event_type == "request":
                # This is a request command
                allowed = bool(int(value_str))
                # Schedule request command
                def request_command():
                    server_sender.handle_request(allowed)
                
                # Schedule the event
                def delayed_request():
                    yield env.timeout(timestamp_ms / 1000.0)
                    request_command()
                
                env.process(delayed_request())
        except Exception as e:
            logging.error(f"Error processing input line: {line} - {e}")

    # Run simulation
    env.run(until=SIMULATION_TIME_MS / 1000.0)
    
    # Finalize simulation
    # Print any remaining events if needed
    logging.info("Simulation finished")

def main():
    parser = argparse.ArgumentParser(description='Dropbox-like synchronization simulation')
    parser.add_argument('--simulation_time', type=float, default=10000000.0, help='Simulation duration in milliseconds')
    args = parser.parse_args()
    
    # Run simulation
    run_simulation(args.simulation_time)

if __name__ == "__main__":
    main()
</python_code>