```python
import argparse
import sys
import json
import logging
import random
import simpy
from collections import deque
from datetime import datetime, timedelta

# Configure logging to stderr
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class EventLogger:
    def __init__(self):
        self.events = []

    def log(self, timestamp_ms, model, event_type, val):
        event = {
            "timestamp_ms": timestamp_ms,
            "model": model,
            "type": event_type,
            "val": val
        }
        self.events.append(event)
        print(json.dumps(event))

class SimTime:
    def __init__(self, simulation_time_ms):
        self.env = simpy.Environment()
        self.simulation_time_ms = simulation_time_ms
        self.event_logger = EventLogger()
        self.running = True

    def run(self):
        # Start all processes
        self.env.process(self.sender_process())
        self.env.process(self.server_receiver_process())
        self.env.process(self.server_sender_process())
        self.env.process(self.receiver_process())
        self.env.process(self.subnet_a1_process())
        self.env.process(self.subnet_a2_process())
        self.env.process(self.subnet_b1_process())
        self.env.process(self.subnet_b2_process())
        self.env.process(self.input_processor())
        self.env.process(self.timeout_check())

        # Run simulation
        self.env.run(until=self.simulation_time_ms)
        # Print all events
        for event in self.event_logger.events:
            print(json.dumps(event))

    def timeout_check(self):
        while self.running:
            yield self.env.timeout(1000)  # Check every second
            if self.env.now > self.simulation_time_ms:
                self.running = False
                break

class Sender:
    def __init__(self, sim_time, event_logger):
        self.sim_time = sim_time
        self.event_logger = event_logger
        self.packets_remaining = 0
        self.current_seq = 1
        self.current_bit = 0
        self.is_busy = False
        self.waiting_for_ack = False
        self.retransmit_count = 0

    def control_cmd(self, n):
        self.packets_remaining += n
        self.event_logger.log(
            self.sim_time.env.now,
            "sender",
            "control_cmd",
            {"added": n, "total_remaining": self.packets_remaining}
        )
        if not self.is_busy:
            self.is_busy = True
            self.sim_time.env.process(self.upload_process())

    def upload_process(self):
        if self.packets_remaining <= 0:
            self.is_busy = False
            return

        # Preparation time
        self.event_logger.log(
            self.sim_time.env.now,
            "sender",
            "preparation_started",
            {"duration": 10000}
        )
        yield self.sim_time.env.timeout(10000)  # 10s preparation

        while self.packets_remaining > 0 and self.is_busy:
            # Send packet
            self.event_logger.log(
                self.sim_time.env.now,
                "sender",
                "packet_sent",
                {"seq": self.current_seq, "bit": self.current_bit, "is_retry": self.retransmit_count > 0}
            )
            self.retransmit_count = 0
            self.waiting_for_ack = True

            # Wait for ACK or timeout
            ack_received = yield self.sim_time.env.event()
            if ack_received:
                # Correct ACK received
                self.event_logger.log(
                    self.sim_time.env.now,
                    "sender",
                    "ack_received",
                    {"bit": self.current_bit}
                )
                self.packets_remaining -= 1
                self.current_bit = 1 - self.current_bit  # Flip bit
                self.current_seq += 1
                self.waiting_for_ack = False
                self.retransmit_count = 0
            else:
                # Timeout or error
                self.event_logger.log(
                    self.sim_time.env.now,
                    "sender",
                    "timeout",
                    {"seq": self.current_seq}
                )
                self.retransmit_count += 1
                if self.retransmit_count >= 3:
                    # Give up after 3 retries
                    self.is_busy = False
                    break
                # Retry sending
                self.waiting_for_ack = False

        if self.packets_remaining <= 0:
            self.is_busy = False

class ServerReceiver:
    def __init__(self, sim_time, event_logger):
        self.sim_time = sim_time
        self.event_logger = event_logger
        self.expected_bit = 0
        self.storage_queue = deque()
        self.packet_processing = False

    def receive_packet(self, packet):
        self.event_logger.log(
            self.sim_time.env.now,
            "server_receiver",
            "packet_received",
            {"seq": packet['seq'], "bit": packet['bit']}
        )

        # Simulate 3s processing delay
        yield self.sim_time.env.timeout(3000)

        if packet['bit'] == self.expected_bit:
            # Valid packet
            self.storage_queue.append(packet)
            self.expected_bit = 1 - self.expected_bit  # Flip expected bit
            self.event_logger.log(
                self.sim_time.env.now,
                "server_receiver",
                "ack_sent_to_sender",
                {"bit": packet['bit']}
            )
        else:
            # Duplicate packet
            self.event_logger.log(
                self.sim_time.env.now,
                "server_receiver",
                "ack_sent_to_sender",
                {"bit": 1 - packet['bit']}  # Send ACK for previous bit
            )

class ServerSender:
    def __init__(self, sim_time, event_logger):
        self.sim_time = sim_time
        self.event_logger = event_logger
        self.download_allowed = False
        self.storage_queue = deque()
        self.current_seq = 1
        self.current_bit = 0
        self.is_busy = False
        self.waiting_for_ack = False

    def download_valve_change(self, allowed):
        self.download_allowed = allowed
        self.event_logger.log(
            self.sim_time.env.now,
            "server_sender",
            "download_valve_change",
            {"allowed": allowed}
        )

    def add_to_storage(self, packet):
        self.storage_queue.append(packet)

    def forward_process(self):
        while self.download_allowed and self.storage_queue and not self.is_busy:
            packet = self.storage_queue.popleft()
            self.event_logger.log(
                self.sim_time.env.now,
                "server_sender",
                "packet_forwarded",
                {"seq": packet['seq'], "bit": packet['bit']}
            )

            self.is_busy = True
            self.waiting_for_ack = True
            self.current_seq = packet['seq']
            self.current_bit = packet['bit']

            # Wait for ACK or timeout
            ack_received = yield self.sim_time.env.event()
            if ack_received:
                self.event_logger.log(
                    self.sim_time.env.now,
                    "server_sender",
                    "ack_received_from_receiver",
                    {"bit": self.current_bit}
                )
                self.is_busy = False
                self.waiting_for_ack = False
            else:
                # Timeout or error
                self.is_busy = False
                self.waiting_for_ack = False
                # Retry next time

class Receiver:
    def __init__(self, sim_time, event_logger):
        self.sim_time = sim_time
        self.event_logger = event_logger

    def receive_data(self, packet):
        self.event_logger.log(
            self.sim_time.env.now,
            "receiver",
            "processing_started",
            {"seq": packet['seq'], "duration": 10000}
        )

        # Simulate 10s processing delay
        yield self.sim_time.env.timeout(10000)

        self.event_logger.log(
            self.sim_time.env.now,
            "receiver",
            "ack_sent",
            {"bit": packet['bit']}
        )

class Subnet:
    def __init__(self, sim_time, event_logger, delay_ms):
        self.sim_time = sim_time
        self.event_logger = event_logger
        self.delay_ms = delay_ms

    def transmit(self, packet):
        yield self.sim_time.env.timeout(self.delay_ms)
        return packet

class Simulation:
    def __init__(self, simulation_time_ms):
        self.sim_time = SimTime(simulation_time_ms)
        self.sender = Sender(self.sim_time, self.sim_time.event_logger)
        self.server_receiver = ServerReceiver(self.sim_time, self.sim_time.event_logger)
        self.server_sender = ServerSender(self.sim_time, self.sim_time.event_logger)
        self.receiver = Receiver(self.sim_time, self.sim_time.event_logger)
        self.subnet_a1 = Subnet(self.sim_time, self.sim_time.event_logger, 3000)  # A1: Sender -> Server
        self.subnet_a2 = Subnet(self.sim_time, self.sim_time.event_logger, 3000)  # A2: Server -> Sender
        self.subnet_b1 = Subnet(self.sim_time, self.sim_time.event_logger, 3000)  # B1: Server -> Receiver
        self.subnet_b2 = Subnet(self.sim_time, self.sim_time.event_logger, 3000)  # B2: Receiver -> Server

    def run(self):
        self.sim_time.run()

    def process_input(self, timestamp_ms, cmd_type, value):
        if cmd_type == "control":
            self.sender.control_cmd(int(value))
        elif cmd_type == "request":
            self.server_sender.download_valve_change(bool(int(value)))

def parse_time(time_str):
    """Parse time string in format HH:MM:SS:mmm"""
    h, m, s, ms = map(int, time_str.split(':'))
    return h * 3600000 + m * 60000 + s * 1000 + ms

def main():
    parser = argparse.ArgumentParser(description="Dropbox-like synchronization simulation")
    parser.add_argument('--simulation_time', type=float, default=10000.0, help='Simulation duration in milliseconds')
    args = parser.parse_args()

    simulation = Simulation(args.simulation_time)

    # Process input from stdin
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        timestamp_str = parts[0]
        cmd_type = parts[1]
        value = parts[2]

        timestamp_ms = parse_time(timestamp_str)
        simulation.process_input(timestamp_ms, cmd_type, value)

    simulation.run()

if __name__ == "__main__":
    main()
</python_code>