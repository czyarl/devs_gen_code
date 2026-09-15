import argparse
import sys
import json
import logging
import collections
import random
import simpy
from xdevs import sim

# Constants
SIMULATION_TIME = 10000_000.0  # Default simulation time in milliseconds

# Logging setup
logging.basicConfig(stream=sys.stderr, level=logging.INFO)

class Sender:
    def __init__(self, env, name):
        self.env = env
        self.name = name
        self.packets_to_send = 0
        self.seq = 1
        self.bit = 0
        self.preparing = False
        self.sending = False
        self.ack_received = False

    def control_cmd(self, added):
        self.packets_to_send += added
        if not self.sending:
            self.start_sending()

    def start_sending(self):
        self.sending = True
        self.preparing = True
        logging.info(f"{self.name} preparation started")
        self.env.process(self.prepare_and_send())

    def prepare_and_send(self):
        yield self.env.timeout(10)
        self.preparing = False
        self.send_packet()

    def send_packet(self):
        if self.packets_to_send > 0:
            logging.info(f"{self.name} packet sent, seq={self.seq}, bit={self.bit}")
            print(json.dumps({
                "timestamp_ms": self.env.now,
                "model": self.name,
                "type": "packet_sent",
                "val": {"seq": self.seq, "bit": self.bit, "is_retry": False}
            }))
            self.env.process(self.wait_for_ack())

    def wait_for_ack(self):
        ack_received = yield self.env.timeout(20)
        if ack_received:
            self.ack_received = True
            logging.info(f"{self.name} ack received, bit={self.bit}")
            print(json.dumps({
                "timestamp_ms": self.env.now,
                "model": self.name,
                "type": "ack_received",
                "val": {"bit": self.bit}
            }))
            self.seq += 1
            self.bit = 1 - self.bit
            self.packets_to_send -= 1
            self.ack_received = False
            if self.packets_to_send > 0:
                self.send_packet()
            else:
                self.sending = False
        else:
            logging.info(f"{self.name} timeout, seq={self.seq}")
            print(json.dumps({
                "timestamp_ms": self.env.now,
                "model": self.name,
                "type": "timeout",
                "val": {"seq": self.seq}
            }))
            self.send_packet()  # Retransmit

class ServerReceiver:
    def __init__(self, env, name):
        self.env = env
        self.name = name
        self.expected_bit = 0
        self.packet_queue = []

    def receive_packet(self, seq, bit):
        logging.info(f"{self.name} packet received, seq={seq}, bit={bit}")
        print(json.dumps({
            "timestamp_ms": self.env.now,
            "model": self.name,
            "type": "packet_received",
            "val": {"seq": seq, "bit": bit}
        }))
        yield self.env.timeout(3)
        if bit == self.expected_bit:
            self.packet_queue.append((seq, bit))
            self.expected_bit = 1 - self.expected_bit
            logging.info(f"{self.name} ack sent to sender, bit={bit}")
            print(json.dumps({
                "timestamp_ms": self.env.now,
                "model": self.name,
                "type": "ack_sent_to_sender",
                "val": {"bit": bit}
            }))

class ServerSender:
    def __init__(self, env, name):
        self.env = env
        self.name = name
        self.packet_queue = []
        self.download_allowed = False
        self.sending = False
        self.bit = 0

    def download_valve_change(self, allowed):
        self.download_allowed = allowed
        logging.info(f"{self.name} download valve change, allowed={allowed}")
        print(json.dumps({
            "timestamp_ms": self.env.now,
            "model": self.name,
            "type": "download_valve_change",
            "val": {"allowed": allowed}
        }))

    def start_sending(self):
        if self.download_allowed and self.packet_queue:
            self.sending = True
            self.send_packet()

    def send_packet(self):
        seq, bit = self.packet_queue.pop(0)
        self.bit = bit
        logging.info(f"{self.name} packet forwarded, seq={seq}, bit={bit}")
        print(json.dumps({
            "timestamp_ms": self.env.now,
            "model": self.name,
            "type": "packet_forwarded",
            "val": {"seq": seq, "bit": bit}
        }))
        self.env.process(self.wait_for_ack(seq, bit))

    def wait_for_ack(self, seq, bit):
        ack_received = yield self.env.timeout(20)
        if ack_received:
            logging.info(f"{self.name} ack received from receiver, bit={bit}")
            print(json.dumps({
                "timestamp_ms": self.env.now,
                "model": self.name,
                "type": "ack_received_from_receiver",
                "val": {"bit": bit}
            }))
            self.sending = False

class Receiver:
    def __init__(self, env, name):
        self.env = env
        self.name = name

    def receive_packet(self, seq, bit):
        logging.info(f"{self.name} processing started, seq={seq}")
        print(json.dumps({
            "timestamp_ms": self.env.now,
            "model": self.name,
            "type": "processing_started",
            "val": {"seq": seq, "duration": 10000}
        }))
        yield self.env.timeout(10)
        logging.info(f"{self.name} ack sent, bit={bit}")
        print(json.dumps({
            "timestamp_ms": self.env.now,
            "model": self.name,
            "type": "ack_sent",
            "val": {"bit": bit}
        }))

def subnet_delay(env, delay):
    yield env.timeout(delay)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=SIMULATION_TIME)
    args = parser.parse_args()

    env = sim.Environment()

    sender = Sender(env, "sender")
    server_receiver = ServerReceiver(env, "server_receiver")
    server_sender = ServerSender(env, "server_sender")
    receiver = Receiver(env, "receiver")

    @sim.register_event_handler("control")
    def control_cmd_handler(event):
        _, value = event.split()
        added = int(value)
        sender.control_cmd(added)
        print(json.dumps({
            "timestamp_ms": env.now,
            "model": "sender",
            "type": "control_cmd",
            "val": {"added": added, "total_remaining": sender.packets_to_send}
        }))

    @sim.register_event_handler("request")
    def request_handler(event):
        _, value = event.split()
        allowed = bool(int(value))
        server_sender.download_valve_change(allowed)

    def input_stream():
        for line in sys.stdin:
            try:
                hour, minute, second, event = line.strip().split()
                second = second.split(":")[0]
                time = int(hour) * 3600 + int(minute) * 60 + int(second)
                env.schedule(time * 1000, event)
            except Exception as e:
                pass

    env.process(input_stream())

    env.run(until=args.simulation_time)

if __name__ == "__main__":
    main()