import argparse
import sys
import json
import logging
import collections
import random
import simpy
from xdevs import *

# Constants
SIMULATION_TIME_MS = 10000_000.0  # Default simulation time in milliseconds

# Logging setup
logging.basicConfig(stream=sys.stderr, level=logging.INFO)

class Sender:
    def __init__(self, env, name):
        self.env = env
        self.name = name
        self.packets_remaining = 0
        self.seq = 1
        self.bit = 0
        self.preparing = False
        self.sending = False
        self.ack_received = False

    def control_cmd(self, added):
        self.packets_remaining += added
        if not self.preparing and not self.sending:
            self.prepare_packet()

    def prepare_packet(self):
        self.preparing = True
        logging.info(f"{self.env.now} {self.name} preparation_started {{'duration': 10000}}")
        print(json.dumps({
            "timestamp_ms": self.env.now,
            "model": self.name,
            "type": "preparation_started",
            "val": {"duration": 10000}
        }))
        self.env.process(self.send_packet())

    def send_packet(self):
        self.preparing = False
        self.sending = True
        logging.info(f"{self.env.now} {self.name} packet_sent {{'seq': {self.seq}, 'bit': {self.bit}, 'is_retry': {self.seq == 1}}}")
        print(json.dumps({
            "timestamp_ms": self.env.now,
            "model": self.name,
            "type": "packet_sent",
            "val": {"seq": self.seq, "bit": self.bit, "is_retry": self.seq == 1}
        }))
        yield self.env.timeout(20)
        if not self.ack_received:
            logging.info(f"{self.env.now} {self.name} timeout {{'seq': {self.seq}}}")
            print(json.dumps({
                "timestamp_ms": self.env.now,
                "model": self.name,
                "type": "timeout",
                "val": {"seq": self.seq}
            }))
            self.send_packet()  # Retransmit
        else:
            self.seq += 1
            self.bit = 1 - self.bit
            self.packets_remaining -= 1
            self.ack_received = False
            if self.packets_remaining > 0:
                self.prepare_packet()
            else:
                self.sending = False

    def receive_ack(self, bit):
        self.ack_received = True
        logging.info(f"{self.env.now} {self.name} ack_received {{'bit': {bit}}}")
        print(json.dumps({
            "timestamp_ms": self.env.now,
            "model": self.name,
            "type": "ack_received",
            "val": {"bit": bit}
        }))

class ServerReceiver:
    def __init__(self, env, name):
        self.env = env
        self.name = name
        self.expected_bit = 0
        self.packet_queue = []

    def receive_packet(self, seq, bit):
        logging.info(f"{self.env.now} {self.name} packet_received {{'seq': {seq}, 'bit': {bit}}}")
        print(json.dumps({
            "timestamp_ms": self.env.now,
            "model": self.name,
            "type": "packet_received",
            "val": {"seq": seq, "bit": bit}
        }))
        yield self.env.timeout(3)
        if bit == self.expected_bit:
            logging.info(f"{self.env.now} {self.name} ack_sent_to_sender {{'bit': {bit}}}")
            print(json.dumps({
                "timestamp_ms": self.env.now,
                "model": self.name,
                "type": "ack_sent_to_sender",
                "val": {"bit": bit}
            }))
            self.packet_queue.append((seq, bit))
            self.expected_bit = 1 - self.expected_bit

class ServerSender:
    def __init__(self, env, name):
        self.env = env
        self.name = name
        self.download_allowed = False
        self.packet_queue = []
        self.sending = False
        self.bit = 0

    def download_valve_change(self, allowed):
        self.download_allowed = allowed
        logging.info(f"{self.env.now} {self.name} download_valve_change {{'allowed': {allowed}}}")
        print(json.dumps({
            "timestamp_ms": self.env.now,
            "model": self.name,
            "type": "download_valve_change",
            "val": {"allowed": allowed}
        }))

    def send_packet(self):
        if self.download_allowed and self.packet_queue:
            seq, bit = self.packet_queue.pop(0)
            self.sending = True
            self.bit = bit
            logging.info(f"{self.env.now} {self.name} packet_forwarded {{'seq': {seq}, 'bit': {bit}}}")
            print(json.dumps({
                "timestamp_ms": self.env.now,
                "model": self.name,
                "type": "packet_forwarded",
                "val": {"seq": seq, "bit": bit}
            }))
            yield self.env.timeout(3)  # Simulating subnet delay
            # Wait for ACK

    def receive_ack(self, bit):
        self.sending = False
        logging.info(f"{self.env.now} {self.name} ack_received_from_receiver {{'bit': {bit}}}")
        print(json.dumps({
            "timestamp_ms": self.env.now,
            "model": self.name,
            "type": "ack_received_from_receiver",
            "val": {"bit": bit}
        }))

class Receiver:
    def __init__(self, env, name):
        self.env = env
        self.name = name

    def receive_packet(self, seq, bit):
        logging.info(f"{self.env.now} {self.name} processing_started {{'seq': {seq}, 'duration': 10000}}")
        print(json.dumps({
            "timestamp_ms": self.env.now,
            "model": self.name,
            "type": "processing_started",
            "val": {"seq": seq, "duration": 10000}
        }))
        yield self.env.timeout(10)
        logging.info(f"{self.env.now} {self.name} ack_sent {{'bit': {bit}}}")
        print(json.dumps({
            "timestamp_ms": self.env.now,
            "model": self.name,
            "type": "ack_sent",
            "val": {"bit": bit}
        }))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=SIMULATION_TIME_MS)
    args = parser.parse_args()

    env = simpy.Environment()
    sender = Sender(env, "sender")
    server_receiver = ServerReceiver(env, "server_receiver")
    server_sender = ServerSender(env, "server_sender")
    receiver = Receiver(env, "receiver")

    def control_cmd_process(line):
        time_str, type, value = line.split()
        time_ms = float(time_str.replace(":", "."))
        env.process(control_cmd(time_ms, type, int(value)))

    def control_cmd(time_ms, type, value):
        if type == "control":
            sender.control_cmd(value)
            logging.info(f"{time_ms} control_cmd {{'added': {value}, 'total_remaining': {sender.packets_remaining}}}")
            print(json.dumps({
                "timestamp_ms": time_ms,
                "model": "sender",
                "type": "control_cmd",
                "val": {"added": value, "total_remaining": sender.packets_remaining}
            }))
        elif type == "request":
            server_sender.download_valve_change(value == 1)

    stdin_lines = sys.stdin.readlines()
    for line in stdin_lines:
        env.process(control_cmd_process(line.strip()))

    def run_simulation():
        yield env.timeout(args.simulation_time / 1000)

    env.process(run_simulation())
    env.run()

if __name__ == "__main__":
    main()