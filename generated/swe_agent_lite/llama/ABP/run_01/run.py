import argparse
import sys
import json
import logging
import collections
import random
import simpy
import xdevs

# Define the simulation parameters
TOTAL_PACKETS = 10
SEED = 42
TIMEOUT = 20
SENDER_DELAY = 10
RECEIVER_DELAY = 10
CHANNEL_DELAY = 3
SIMULATE_TIME = 1000

# Define the ABP simulation
class ABPSimulation:
    def __init__(self, env, total_packets, seed, timeout, sender_delay, receiver_delay, channel_delay):
        self.env = env
        self.total_packets = total_packets
        self.seed = seed
        self.timeout = timeout
        self.sender_delay = sender_delay
        self.receiver_delay = receiver_delay
        self.channel_delay = channel_delay
        self.noise_level = seed
        self.packet_seq_num = 1
        self.sender_preparation_delay = self.env.process(self.sender_preparation_delay_process())

    def sender_preparation_delay_process(self):
        while self.packet_seq_num <= self.total_packets:
            yield self.env.timeout(self.sender_delay / 1000)
            # Send packet
            self.send_packet()

    def send_packet(self):
        # Calculate packet bit
        bit = (self.packet_seq_num - 1) % 2
        # Create packet
        packet = {'seq_num': self.packet_seq_num, 'bit': bit}
        # Send packet through subnet
        self.subnet_send(packet)
        # Start timer
        self.env.process(self.timer_process(packet))
        self.packet_seq_num += 1

    def subnet_send(self, packet):
        # Calculate noise level
        self.noise_level = (17 * self.noise_level + 11) % 100
        if self.noise_level < 10:
            # Packet dropped
            print(json.dumps({'time': self.env.now, 'entity': 'subnet', 'event': 'packet_get', 'payload': {'behavior': 'drop', 'channel': 'forward', 'noise_value': self.noise_level}}))
        else:
            # Packet transmitted
            print(json.dumps({'time': self.env.now, 'entity': 'subnet', 'event': 'packet_get', 'payload': {'behavior': 'pass', 'channel': 'forward', 'noise_value': self.noise_level}}))
            # Send packet to receiver
            self.receiver_receive(packet)

    def receiver_receive(self, packet):
        # Start processing delay
        self.env.process(self.receiver_processing_delay_process(packet))

    def receiver_processing_delay_process(self, packet):
        yield self.env.timeout(self.receiver_delay / 1000)
        # Process packet
        print(json.dumps({'time': self.env.now, 'entity': 'receiver', 'event': 'packet_received', 'payload': packet}))
        # Send ACK
        ack = {'bit': packet['bit']}
        self.subnet_send_ack(ack)

    def subnet_send_ack(self, ack):
        # Calculate noise level
        self.noise_level = (17 * self.noise_level + 11) % 100
        if self.noise_level < 10:
            # ACK dropped
            print(json.dumps({'time': self.env.now, 'entity': 'subnet', 'event': 'packet_get', 'payload': {'behavior': 'drop', 'channel': 'backward', 'noise_value': self.noise_level}}))
        else:
            # ACK transmitted
            print(json.dumps({'time': self.env.now, 'entity': 'subnet', 'event': 'packet_get', 'payload': {'behavior': 'pass', 'channel': 'backward', 'noise_value': self.noise_level}}))
            # Send ACK to sender
            self.sender_receive_ack(ack)

    def sender_receive_ack(self, ack):
        # Check ACK validity
        if ack['bit'] == (self.packet_seq_num - 1) % 2:
            print(json.dumps({'time': self.env.now, 'entity': 'sender', 'event': 'ack_received', 'payload': {'ack_bit': ack['bit'], 'is_valid': True}}))
        else:
            print(json.dumps({'time': self.env.now, 'entity': 'sender', 'event': 'ack_received', 'payload': {'ack_bit': ack['bit'], 'is_valid': False}}))

    def timer_process(self, packet):
        yield self.env.timeout(self.timeout / 1000)
        # Retransmit packet if timer expired
        if self.packet_seq_num > packet['seq_num']:
            self.send_packet()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--total_packets', type=int, default=TOTAL_PACKETS)
    parser.add_argument('--seed', type=int, default=SEED)
    parser.add_argument('--timeout', type=int, default=TIMEOUT)
    parser.add_argument('--sender_delay', type=int, default=SENDER_DELAY)
    parser.add_argument('--receiver_delay', type=int, default=RECEIVER_DELAY)
    parser.add_argument('--channel_delay', type=int, default=CHANNEL_DELAY)
    parser.add_argument('--simulate_time', type=int, default=SIMULATE_TIME)
    args = parser.parse_args()
    env = simpy.Environment()
    abp_simulation = ABPSimulation(env, args.total_packets, args.seed, args.timeout, args.sender_delay, args.receiver_delay, args.channel_delay)
    env.run(until=args.simulate_time / 1000)

if __name__ == '__main__':
    main()
