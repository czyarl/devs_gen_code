import argparse
import sys
import json
import logging
import random
import simpy
from collections import deque

# Constants
TIME_UNIT = 1  # Milliseconds

class NoiseModel:
    def __init__(self, seed):
        self.noise_level = seed

    def update_noise(self):
        self.noise_level = (17 * self.noise_level + 11) % 100
        return self.noise_level

class Subnet:
    def __init__(self, env, name, delay, noise_model):
        self.env = env
        self.name = name
        self.delay = delay
        self.noise_model = noise_model
        self.logger = logging.getLogger(f"Subnet {name}")

    def transmit_packet(self, packet):
        noise_value = self.noise_model.update_noise()
        if noise_value < 10:
            self.logger.debug(f"Packet dropped due to high interference. Noise value: {noise_value}")
            print(json.dumps({"time": self.env.now, "entity": self.name, "event": "packet_get", "payload": {"behavior": "drop", "channel": "forward" if self.name == "Subnet1" else "backward", "noise_value": noise_value}}))
            return False
        else:
            self.logger.debug(f"Packet transmitted normally. Noise value: {noise_value}")
            print(json.dumps({"time": self.env.now, "entity": self.name, "event": "packet_get", "payload": {"behavior": "pass", "channel": "forward" if self.name == "Subnet1" else "backward", "noise_value": noise_value}}))
            yield self.env.timeout(self.delay / 1000)
            return True

class Sender:
    def __init__(self, env, total_packets, timeout, delay, subnet1):
        self.env = env
        self.total_packets = total_packets
        self.timeout = timeout
        self.delay = delay
        self.subnet1 = subnet1
        self.seq_num = 1
        self.bit = 0
        self.sent_packets = {}
        self.logger = logging.getLogger("Sender")

    def send_packet(self):
        self.logger.debug("Sender starts preparation delay")
        print(json.dumps({"time": self.env.now, "entity": "sender", "event": "delay_start", "payload": {"type": "preparation", "duration": self.delay}}))
        yield self.env.timeout(self.delay / 1000)
        self.logger.debug(f"Sender sends packet {self.seq_num} with bit {self.bit}")
        print(json.dumps({"time": self.env.now, "entity": "sender", "event": "packet_sent", "payload": {"seq_num": self.seq_num, "bit": self.bit, "is_retry": False}}))
        self.sent_packets[self.seq_num] = self.bit
        self.bit = 1 - self.bit
        self.seq_num += 1

        # Simulate transmission and wait for ACK
        if (yield self.subnet1.transmit_packet({"seq_num": self.seq_num - 1, "bit": self.sent_packets[self.seq_num - 1]})):
            yield self.env.timeout(self.timeout / 1000)
            # Process ACK

    def run(self):
        for _ in range(self.total_packets):
            yield self.env.process(self.send_packet())

class Receiver:
    def __init__(self, env, delay, subnet2):
        self.env = env
        self.delay = delay
        self.subnet2 = subnet2
        self.logger = logging.getLogger("Receiver")
        self.buffer = None

    def process_packet(self, packet):
        self.logger.debug("Receiver starts processing delay")
        print(json.dumps({"time": self.env.now, "entity": "receiver", "event": "delay_start", "payload": {"type": "processing", "duration": self.delay}}))
        yield self.env.timeout(self.delay / 1000)
        self.logger.debug(f"Receiver processes packet {packet['seq_num']} with bit {packet['bit']}")
        print(json.dumps({"time": self.env.now, "entity": "receiver", "event": "packet_received", "payload": {"seq_num": packet['seq_num'], "bit": packet['bit']}}))
        # Send ACK
        ack_packet = {"bit": packet['bit']}
        self.logger.debug(f"Receiver sends ACK with bit {ack_packet['bit']}")
        if (yield self.subnet2.transmit_packet(ack_packet)):
            pass

    def run(self):
        while True:
            packet = yield self.env.event()
            if packet:
                yield self.env.process(self.process_packet(packet))

def main():
    parser = argparse.ArgumentParser(description="Reliable Data Transfer Simulation")
    parser.add_argument("--total_packets", type=int, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--sender_delay", type=int, default=10)
    parser.add_argument("--receiver_delay", type=int, default=10)
    parser.add_argument("--channel_delay", type=int, default=3)
    parser.add_argument("--simulate_time", type=int, default=1000)

    args = parser.parse_args()

    logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)

    env = simpy.Environment()

    noise_model1 = NoiseModel(args.seed)
    noise_model2 = NoiseModel(args.seed)
    subnet1 = Subnet(env, "Subnet1", args.channel_delay, noise_model1)
    subnet2 = Subnet(env, "Subnet2", args.channel_delay, noise_model2)

    sender = Sender(env, args.total_packets, args.timeout, args.sender_delay, subnet1)
    receiver = Receiver(env, args.receiver_delay, subnet2)

    def event_generator():
        for i in range(args.total_packets):
            yield env.process(sender.run())

    env.process(event_generator())

    env.run(until=args.simulate_time / 1000)

if __name__ == "__main__":
    main()