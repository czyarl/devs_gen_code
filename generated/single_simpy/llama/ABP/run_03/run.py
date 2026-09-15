import argparse
import sys
import json
import logging
import random
import simpy
from collections import defaultdict

# Logging Configuration
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(message)s')

# Constants
TIME_UNIT = 1.0  # Milliseconds

class Subnet:
    def __init__(self, env, name, delay, seed):
        self.env = env
        self.name = name
        self.delay = delay
        self.noise_seed = seed
        self.noise_level = seed

    def calculate_noise(self):
        self.noise_level = (17 * self.noise_level + 11) % 100

    def determine_packet_fate(self):
        self.calculate_noise()
        if self.noise_level < 10:
            return "drop"
        else:
            return "pass"

    def transmit_packet(self, packet):
        fate = self.determine_packet_fate()
        logging.info(f"Subnet {self.name} noise level: {self.noise_level}, fate: {fate}")
        if fate == "drop":
            return
        else:
            yield self.env.timeout(self.delay / 1000)

class Sender:
    def __init__(self, env, name, subnet, receiver, timeout, delay, total_packets):
        self.env = env
        self.name = name
        self.subnet = subnet
        self.receiver = receiver
        self.timeout = timeout / 1000
        self.delay = delay / 1000
        self.total_packets = total_packets
        self.seq_num = 1
        self.bit = 0
        self.sent_packets = {}
        self.waiting_for_ack = False

    def start_preparation_delay(self):
        print(json.dumps({"time": self.env.now, "entity": self.name, "event": "delay_start", "payload": {"type": "preparation", "duration": self.delay * 1000}}))
        yield self.env.timeout(self.delay)

    def send_packet(self):
        while self.seq_num <= self.total_packets:
            yield self.start_preparation_delay()
            packet = {"seq_num": self.seq_num, "bit": self.bit}
            print(json.dumps({"time": self.env.now, "entity": self.name, "event": "packet_sent", "payload": {"seq_num": packet["seq_num"], "bit": packet["bit"], "is_retry": False}}))
            self.sent_packets[self.seq_num] = packet
            self.waiting_for_ack = True
            self.subnet.transmit_packet(packet)
            yield self.env.timeout(self.timeout)
            if self.waiting_for_ack:
                if self.seq_num not in self.sent_packets:
                    continue
                packet = self.sent_packets[self.seq_num]
                self.bit = 1 - self.bit
                self.seq_num += 1
                self.waiting_for_ack = False

class Receiver:
    def __init__(self, env, name, subnet, delay):
        self.env = env
        self.name = name
        self.subnet = subnet
        self.delay = delay / 1000

    def process_packet(self, packet):
        print(json.dumps({"time": self.env.now, "entity": self.name, "event": "delay_start", "payload": {"type": "processing", "duration": self.delay * 1000}}))
        yield self.env.timeout(self.delay)
        print(json.dumps({"time": self.env.now, "entity": self.name, "event": "packet_received", "payload": {"seq_num": packet["seq_num"], "bit": packet["bit"]}}))

def main():
    parser = argparse.ArgumentParser(description='Reliable Data Transfer Simulation')
    parser.add_argument('--total_packets', type=int, required=True, help='Total number of packets to send')
    parser.add_argument('--seed', type=int, default=42, help='Initialization seed for noise generator')
    parser.add_argument('--timeout', type=int, default=20, help='Sender timeout duration in ms')
    parser.add_argument('--sender_delay', type=int, default=10, help='Sender preparation delay in ms')
    parser.add_argument('--receiver_delay', type=int, default=10, help='Receiver processing delay in ms')
    parser.add_argument('--channel_delay', type=int, default=3, help='Subnet transmission delay in ms')
    parser.add_argument('--simulate_time', type=int, default=1000, help='Total simulation time in ms')
    args = parser.parse_args()

    env = simpy.Environment()
    subnet1 = Subnet(env, "Subnet1", args.channel_delay, args.seed)
    subnet2 = Subnet(env, "Subnet2", args.channel_delay, args.seed)
    receiver = Receiver(env, "receiver", subnet1, args.receiver_delay)
    sender = Sender(env, "sender", subnet1, receiver, args.timeout, args.sender_delay, args.total_packets)

    def run_simulation():
        env.process(sender.send_packet())
        try:
            env.run(until=args.simulate_time / 1000)
        except Exception as e:
            logging.error(f"Simulation failed: {e}")

    run_simulation()

if __name__ == "__main__":
    main()