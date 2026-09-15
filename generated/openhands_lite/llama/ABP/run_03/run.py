#!/usr/bin/env python3.10
import argparse
import json
import logging
import random
import simpy

# Define constants
DEFAULT_SEED = 42
DEFAULT_TIMEOUT = 20
DEFAULT_SENDER_DELAY = 10
DEFAULT_RECEIVER_DELAY = 10
DEFAULT_CHANNEL_DELAY = 3
DEFAULT_SIMULATE_TIME = 1000

# Define event types
EVENT_TYPES = {
    'delay_start': 'delay_start',
    'packet_sent': 'packet_sent',
    'ack_received': 'ack_received',
    'packet_received': 'packet_received'
}

class Packet:
    def __init__(self, seq_num, bit):
        self.seq_num = seq_num
        self.bit = bit

class Subnet:
    def __init__(self, env):
        self.env = env
        self.noise_level = random.seed(DEFAULT_SEED)

    def determine_packet_fate(self, packet):
        new_noise_level = (17 * self.noise_level + 11) % 100
        self.noise_level = new_noise_level
        if new_noise_level < 10:
            return 'drop'
        else:
            return 'pass'

class Sender:
    def __init__(self, env, total_packets, timeout, delay):
        self.env = env
        self.total_packets = total_packets
        self.timeout = timeout
        self.delay = delay
        self.seq_num = 1
        self.bit = 0
        self.acked = False

    def send_packet(self, subnet):
        packet = Packet(self.seq_num, self.bit)
        logging.info(f'Sender: Send packet {packet.seq_num} with bit {packet.bit}')
        # Simulate packet sending
        yield self.env.timeout(self.delay / 1000)
        fate = subnet.determine_packet_fate(packet)
        if fate == 'drop':
            logging.info(f'Subnet: Drop packet {packet.seq_num}')
        else:
            # Simulate packet transmission delay
            yield self.env.timeout(DEFAULT_CHANNEL_DELAY / 1000)
            logging.info(f'Receiver: Receive packet {packet.seq_num}')
            # Receiver processing delay
            yield self.env.timeout(DEFAULT_RECEIVER_DELAY / 1000)
            # Send ACK
            ack_bit = packet.bit
            logging.info(f'Sender: Receive ACK {ack_bit}')
            self.acked = True

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--total_packets', type=int, default=10)
    parser.add_argument('--seed', type=int, default=DEFAULT_SEED)
    parser.add_argument('--timeout', type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument('--sender_delay', type=int, default=DEFAULT_SENDER_DELAY)
    parser.add_argument('--receiver_delay', type=int, default=DEFAULT_RECEIVER_DELAY)
    parser.add_argument('--channel_delay', type=int, default=DEFAULT_CHANNEL_DELAY)
    parser.add_argument('--simulate_time', type=int, default=DEFAULT_SIMULATE_TIME)
    args = parser.parse_args()

    env = simpy.Environment()
    subnet = Subnet(env)
    sender = Sender(env, args.total_packets, args.timeout, args.sender_delay)

    def event_generator():
        while True:
            yield env.timeout(1)

    env.process(event_generator())

if __name__ == '__main__':
    main()