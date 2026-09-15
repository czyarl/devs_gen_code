import argparse
import sys
import json
import logging
import collections
import random
import simpy
import time
import math

# Set up logging
logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)

# Define constants
SIMULATION_TIME_MS = 10_000_000.0  # Default simulation time in milliseconds

# Define event types
EVENT_TYPES = {
    "control_cmd": "control_cmd",
    "download_valve_change": "download_valve_change",
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

class Entity:
    def __init__(self, name, env):
        self.name = name
        self.env = env

class Sender(Entity):
    def __init__(self, name, env):
        super().__init__(name, env)
        self.packets_remaining = 0
        self.seq = 1
        self.bit = 0
        self.preparing = False
        self.sending = False

    def control_cmd(self, added):
        self.packets_remaining += added
        if not self.sending and self.packets_remaining > 0:
            self.start_sending()

    def start_sending(self):
        self.preparing = True
        self.env.process(self.prepare_and_send())

    def prepare_and_send(self):
        yield self.env.timeout(10 / 1000)  # 10s preparation
        self.preparing = False
        self.sending = True
        self.packet_sent(seq=self.seq, bit=self.bit, is_retry=False)

    def packet_sent(self, seq, bit, is_retry):
        print(json.dumps({
            "timestamp_ms": self.env.now * 1000,
            "model": self.name,
            "type": EVENT_TYPES["packet_sent"],
            "val": {"seq": seq, "bit": bit, "is_retry": is_retry}
        }))

        # Wait for ACK
        yield self.env.timeout(20 / 1000)  # 20s timeout

        # Check if ACK received
        if self.bit == self.expected_bit:
            self.ack_received(bit=self.bit)
            self.seq += 1
            self.bit = 1 - self.bit
            self.packets_remaining -= 1
            if self.packets_remaining == 0:
                self.sending = False
        else:
            self.timeout(seq=self.seq)

    def ack_received(self, bit):
        print(json.dumps({
            "timestamp_ms": self.env.now * 1000,
            "model": self.name,
            "type": EVENT_TYPES["ack_received"],
            "val": {"bit": bit}
        }))

    def timeout(self, seq):
        print(json.dumps({
            "timestamp_ms": self.env.now * 1000,
            "model": self.name,
            "type": EVENT_TYPES["timeout"],
            "val": {"seq": seq}
        }))
        self.packet_sent(seq=self.seq, bit=self.bit, is_retry=True)

class ServerReceiver(Entity):
    def __init__(self, name, env):
        super().__init__(name, env)
        self.expected_bit = 0
        self.storage_queue = collections.deque()

    def packet_received(self, seq, bit):
        print(json.dumps({
            "timestamp_ms": self.env.now * 1000,
            "model": self.name,
            "type": EVENT_TYPES["packet_received"],
            "val": {"seq": seq, "bit": bit}
        }))
        yield self.env.timeout(3 / 1000)  # 3s processing delay
        if bit == self.expected_bit:
            self.storage_queue.append((seq, bit))
            self.expected_bit = 1 - self.expected_bit
            self.ack_sent_to_sender(bit=self.expected_bit)

    def ack_sent_to_sender(self, bit):
        print(json.dumps({
            "timestamp_ms": self.env.now * 1000,
            "model": self.name,
            "type": EVENT_TYPES["ack_sent_to_sender"],
            "val": {"bit": bit}
        }))

class ServerSender(Entity):
    def __init__(self, name, env):
        super().__init__(name, env)
        self.download_allowed = False
        self.storage_queue = collections.deque()
        self.seq = 1
        self.bit = 0

    def download_valve_change(self, allowed):
        self.download_allowed = allowed

    def packet_forwarded(self, seq, bit):
        print(json.dumps({
            "timestamp_ms": self.env.now * 1000,
            "model": self.name,
            "type": EVENT_TYPES["packet_forwarded"],
            "val": {"seq": seq, "bit": bit}
        }))

    def ack_received_from_receiver(self, bit):
        print(json.dumps({
            "timestamp_ms": self.env.now * 1000,
            "model": self.name,
            "type": EVENT_TYPES["ack_received_from_receiver"],
            "val": {"bit": bit}
        }))

class Receiver(Entity):
    def __init__(self, name, env):
        super().__init__(name, env)
        self.seq = 1
        self.bit = 0

    def processing_started(self, seq):
        print(json.dumps({
            "timestamp_ms": self.env.now * 1000,
            "model": self.name,
            "type": EVENT_TYPES["processing_started"],
            "val": {"seq": seq, "duration": 10000}
        }))
        yield self.env.timeout(10 / 1000)  # 10s processing delay
        self.ack_sent(bit=self.bit)

    def ack_sent(self, bit):
        print(json.dumps({
            "timestamp_ms": self.env.now * 1000,
            "model": self.name,
            "type": EVENT_TYPES["ack_sent"],
            "val": {"bit": bit}
        }))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=SIMULATION_TIME_MS)
    args = parser.parse_args()

    env = simpy.Environment()
    sender = Sender("sender", env)
    server_receiver = ServerReceiver("server_receiver", env)
    server_sender = ServerSender("server_sender", env)
    receiver = Receiver("receiver", env)

    def control_cmd_process(line):
        time_str, type, value = line.split()
        if type == "control":
            value = int(value)
            sender.control_cmd(value)
            print(json.dumps({
                "timestamp_ms": env.now * 1000,
                "model": sender.name,
                "type": EVENT_TYPES["control_cmd"],
                "val": {"added": value, "total_remaining": sender.packets_remaining}
            }))
        elif type == "request":
            value = int(value)
            server_sender.download_valve_change(value == 1)
            print(json.dumps({
                "timestamp_ms": env.now * 1000,
                "model": server_sender.name,
                "type": EVENT_TYPES["download_valve_change"],
                "val": {"allowed": value == 1}
            }))

    for line in sys.stdin:
        line = line.strip()
        if line:
            control_cmd_process(line)

    def simulation():
        yield env.timeout(args.simulation_time / 1000)

    env.process(simulation())
    env.run()

if __name__ == "__main__":
    main()