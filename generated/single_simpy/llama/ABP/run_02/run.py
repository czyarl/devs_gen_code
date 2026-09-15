import argparse
import sys
import json
import logging
import random
import simpy
import xdevs

# Constants
DEFAULT_SEED = 42

class ReliableDataTransfer:
    def __init__(self, env, total_packets, seed, timeout, sender_delay, receiver_delay, channel_delay, simulate_time):
        self.env = env
        self.total_packets = total_packets
        self.seed = seed
        self.timeout = timeout / 1000  # Convert to seconds
        self.sender_delay = sender_delay / 1000
        self.receiver_delay = receiver_delay / 1000
        self.channel_delay = channel_delay / 1000
        self.simulate_time = simulate_time / 1000
        self.sender_noise = seed
        self.receiver_noise = seed
        self.sender_bit = 0
        self.packet_seq_num = 1
        self.expected_ack_bit = 0
        self.sent_packet = None
        self.acked = False

        self.subnet1 = env.process(self.subnet_process("subnet1", self.sender_noise, "forward"))
        self.subnet2 = env.process(self.subnet_process("subnet2", self.receiver_noise, "backward"))

        self.sender_process = env.process(self.sender())
        self.receiver_process = env.process(self.receiver())

    def subnet_process(self, name, noise, direction):
        noise_value = noise
        while True:
            packet = yield self.env.event()
            noise_value = (17 * noise_value + 11) % 100
            if noise_value < 10:
                print(json.dumps({"time": self.env.now, "entity": name, "event": "packet_get", "payload": {"behavior": "drop", "channel": direction, "noise_value": noise_value}}), file=sys.stderr)
                continue
            else:
                print(json.dumps({"time": self.env.now, "entity": name, "event": "packet_get", "payload": {"behavior": "pass", "channel": direction, "noise_value": noise_value}}), file=sys.stderr)
                if direction == "forward":
                    self.env.process(self.transmit_packet(packet, self.channel_delay))
                else:
                    self.env.process(self.ack_packet(packet, self.channel_delay))
            noise = noise_value

    def sender(self):
        for _ in range(self.total_packets):
            yield self.env.timeout(self.sender_delay)
            print(json.dumps({"time": self.env.now, "entity": "sender", "event": "delay_start", "payload": {"type": "preparation", "duration": self.sender_delay}}))
            packet = {"seq_num": self.packet_seq_num, "bit": self.sender_bit}
            self.sent_packet = packet
            print(json.dumps({"time": self.env.now, "entity": "sender", "event": "packet_sent", "payload": {"seq_num": packet["seq_num"], "bit": packet["bit"], "is_retry": False}}))
            self.packet_seq_num += 1
            self.sender_bit = 1 - self.sender_bit
            self.acked = False
            timer = self.env.timeout(self.timeout)
            ack_received = self.env.event()
            yield self.env.any_of(timer, ack_received)
            if self.acked:
                continue
            else:
                print(json.dumps({"time": self.env.now, "entity": "sender", "event": "packet_sent", "payload": {"seq_num": self.sent_packet["seq_num"], "bit": self.sent_packet["bit"], "is_retry": True}}))

    def receiver(self):
        while True:
            packet = yield self.env.event()
            yield self.env.timeout(self.receiver_delay)
            print(json.dumps({"time": self.env.now, "entity": "receiver", "event": "delay_start", "payload": {"type": "processing", "duration": self.receiver_delay}}))
            print(json.dumps({"time": self.env.now, "entity": "receiver", "event": "packet_received", "payload": {"seq_num": packet["seq_num"], "bit": packet["bit"]}}))
            ack_packet = {"bit": packet["bit"]}
            self.env.process(self.send_ack(ack_packet))

    def transmit_packet(self, packet, delay):
        yield self.env.timeout(delay)

    def ack_packet(self, packet, delay):
        yield self.env.timeout(delay)
        self.env.process(self.receiver_process.put(packet))

    def send_ack(self, packet):
        self.env.process(self.subnet2.put(packet))

def main():
    parser = argparse.ArgumentParser(description='Reliable Data Transfer Simulation')
    parser.add_argument('--total_packets', type=int, required=True)
    parser.add_argument('--seed', type=int, default=DEFAULT_SEED)
    parser.add_argument('--timeout', type=int, default=20)
    parser.add_argument('--sender_delay', type=int, default=10)
    parser.add_argument('--receiver_delay', type=int, default=10)
    parser.add_argument('--channel_delay', type=int, default=3)
    parser.add_argument('--simulate_time', type=int, default=1000)
    args = parser.parse_args()

    env = simpy.Environment()
    rdt = ReliableDataTransfer(env, args.total_packets, args.seed, args.timeout, args.sender_delay, args.receiver_delay, args.channel_delay, args.simulate_time)
    env.run(until=args.simulate_time / 1000)

if __name__ == "__main__":
    main()