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

# Define the event types
EVENT_TYPES = {
    'delay_start': 'delay_start',
    'packet_sent': 'packet_sent',
    'ack_received': 'ack_received',
    'packet_received': 'packet_received'
}

# Define the entity types
ENTITY_TYPES = {
    'sender': 'sender',
    'receiver': 'receiver',
    'subnet': 'subnet'
}

class Sender:
    def __init__(self, env, total_packets, timeout, delay):
        self.env = env
        self.total_packets = total_packets
        self.timeout = timeout
        self.delay = delay
        self.packet_sent = 0
        self.ack_received = False

    def send_packet(self):
        while self.packet_sent < self.total_packets:
            # Start preparation delay
            yield self.env.timeout(self.delay / 1000)
            print(json.dumps({
                'time': self.env.now,
                'entity': ENTITY_TYPES['sender'],
                'event': EVENT_TYPES['delay_start'],
                'payload': {
                    'type': 'preparation',
                    'duration': self.delay
                }
            }))

            # Send packet
            self.packet_sent += 1
            bit = self.packet_sent % 2
            print(json.dumps({
                'time': self.env.now,
                'entity': ENTITY_TYPES['sender'],
                'event': EVENT_TYPES['packet_sent'],
                'payload': {
                    'seq_num': self.packet_sent,
                    'bit': bit,
                    'is_retry': False
                }
            }))

            # Start timer
            timer = self.env.timeout(self.timeout / 1000)
            yield timer

            # Check if ACK is received
            if not self.ack_received:
                # Retransmit packet
                print(json.dumps({
                    'time': self.env.now,
                    'entity': ENTITY_TYPES['sender'],
                    'event': EVENT_TYPES['packet_sent'],
                    'payload': {
                        'seq_num': self.packet_sent,
                        'bit': bit,
                        'is_retry': True
                    }
                }))
            else:
                self.ack_received = False

    def receive_ack(self, ack_bit):
        print(json.dumps({
            'time': self.env.now,
            'entity': ENTITY_TYPES['sender'],
            'event': EVENT_TYPES['ack_received'],
            'payload': {
                'ack_bit': ack_bit,
                'is_valid': True
            }
        }))
        self.ack_received = True

class Receiver:
    def __init__(self, env, delay):
        self.env = env
        self.delay = delay
        self.packet_received = 0

    def receive_packet(self, packet):
        # Start processing delay
        yield self.env.timeout(self.delay / 1000)
        print(json.dumps({
            'time': self.env.now,
            'entity': ENTITY_TYPES['receiver'],
            'event': EVENT_TYPES['delay_start'],
            'payload': {
                'type': 'processing',
                'duration': self.delay
            }
        }))

        # Process packet
        self.packet_received += 1
        bit = packet['bit']
        print(json.dumps({
            'time': self.env.now,
            'entity': ENTITY_TYPES['receiver'],
            'event': EVENT_TYPES['packet_received'],
            'payload': {
                'seq_num': packet['seq_num'],
                'bit': bit
            }
        }))

        # Send ACK
        yield self.env.timeout(CHANNEL_DELAY / 1000)
        print(json.dumps({
            'time': self.env.now,
            'entity': ENTITY_TYPES['subnet'],
            'event': 'packet_get',
            'payload': {
                'behavior': 'pass',
                'channel': 'backward',
                'noise_value': 0
            }
        }))

class Subnet:
    def __init__(self, env, delay):
        self.env = env
        self.delay = delay
        self.noise_level = SEED

    def transmit_packet(self, packet):
        # Calculate noise level
        self.noise_level = (17 * self.noise_level + 11) % 100
        if self.noise_level < 10:
            # Drop packet
            print(json.dumps({
                'time': self.env.now,
                'entity': ENTITY_TYPES['subnet'],
                'event': 'packet_get',
                'payload': {
                    'behavior': 'drop',
                    'channel': 'forward',
                    'noise_value': self.noise_level
                }
            }))
            return

        # Transmit packet
        yield self.env.timeout(self.delay / 1000)
        print(json.dumps({
            'time': self.env.now,
            'entity': ENTITY_TYPES['subnet'],
            'event': 'packet_get',
            'payload': {
                'behavior': 'pass',
                'channel': 'forward',
                'noise_value': self.noise_level
            }
        }))

def main():
    env = simpy.Environment()
    sender = Sender(env, TOTAL_PACKETS, TIMEOUT, SENDER_DELAY)
    receiver = Receiver(env, RECEIVER_DELAY)
    subnet = Subnet(env, CHANNEL_DELAY)

    env.process(sender.send_packet())
    env.run(until=SIMULATE_TIME / 1000)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--total_packets', type=int, default=TOTAL_PACKETS)
    parser.add_argument('--seed', type=int, default=SEED)
    parser.add_argument('--timeout', type=int, default=TIMEOUT)
    parser.add_argument('--sender_delay', type=int, default=SENDER_DELAY)
    parser.add_argument('--receiver_delay', type=int, default=RECEIVER_DELAY)
    parser.add_argument('--channel_delay', type=int, default=CHANNEL_DELAY)
    parser.add_argument('--simulate_time', type=int, default=SIMULATE_TIME)
    args = parser.parse_args()

    TOTAL_PACKETS = args.total_packets
    SEED = args.seed
    TIMEOUT = args.timeout
    SENDER_DELAY = args.sender_delay
    RECEIVER_DELAY = args.receiver_delay
    CHANNEL_DELAY = args.channel_delay
    SIMULATE_TIME = args.simulate_time

    main()