import argparse
import json
import logging
import random
import sys
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

class Sender(Atomic):
    def __init__(self, name: str, parent: Coupled | None, total_packets: int, sender_delay: float, timeout: float):
        super().__init__(name)
        self.parent = parent
        self.total_packets = total_packets
        self.sender_delay = sender_delay
        self.timeout = timeout
        self.add_in_port(Port("ack", "in_ack"))
        self.add_out_port(Port("packet", "out_packet"))
        self.seq_num = 1
        self.bit = 0
        self.packet_sent = False
        self.ack_received = False
        self.timer_active = False

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        if not self.packet_sent:
            self.output["out_packet"].add({"seq_num": self.seq_num, "bit": self.bit, "is_retry": False})
            print(json.dumps({"time": self.time, "entity": "sender", "event": "packet_sent", "payload": {"seq_num": self.seq_num, "bit": self.bit, "is_retry": False}}), file=sys.stdout, flush=True)
            self.packet_sent = True
            self.timer_active = True
            self.hold_in("WAIT_ACK", self.timeout)
        elif self.timer_active:
            self.output["out_packet"].add({"seq_num": self.seq_num, "bit": self.bit, "is_retry": True})
            print(json.dumps({"time": self.time, "entity": "sender", "event": "packet_sent", "payload": {"seq_num": self.seq_num, "bit": self.bit, "is_retry": True}}), file=sys.stdout, flush=True)
            self.hold_in("WAIT_ACK", self.timeout)

    def deltext(self, e):
        if self.input["in_ack"].values:
            ack_bit = self.input["in_ack"].values[0]
            self.ack_received = True
            self.timer_active = False
            if ack_bit == self.bit:
                self.seq_num += 1
                self.bit = 1 - self.bit
                self.packet_sent = False
                self.ack_received = False
                self.hold_in("SEND_PACKET", self.sender_delay)
            else:
                self.hold_in("WAIT_ACK", 0)

    def exit(self):
        pass

class Receiver(Atomic):
    def __init__(self, name: str, parent: Coupled | None, receiver_delay: float):
        super().__init__(name)
        self.parent = parent
        self.receiver_delay = receiver_delay
        self.add_in_port(Port("packet", "in_packet"))
        self.add_out_port(Port("ack", "out_ack"))
        self.buffer = None

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        if self.input["in_packet"].values:
            packet = self.input["in_packet"].values[0]
            self.buffer = packet
            print(json.dumps({"time": self.time, "entity": "receiver", "event": "packet_received", "payload": {"seq_num": packet["seq_num"], "bit": packet["bit"]}}), file=sys.stdout, flush=True)
            self.output["out_ack"].add(packet["bit"])
            print(json.dumps({"time": self.time, "entity": "receiver", "event": "delay_start", "payload": {"type": "processing", "duration": self.receiver_delay}}), file=sys.stdout, flush=True)
            self.hold_in("PROCESS_PACKET", self.receiver_delay)

    def exit(self):
        pass

class Subnet(Atomic):
    def __init__(self, name: str, parent: Coupled | None, channel_delay: float, seed: int, direction: str):
        super().__init__(name)
        self.parent = parent
        self.channel_delay = channel_delay
        self.seed = seed
        self.direction = direction
        self.add_in_port(Port("packet", "in_packet"))
        self.noise_level = self.seed

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        if self.input["in_packet"].values:
            packet = self.input["in_packet"].values[0]
            self.noise_level = (17 * self.noise_level + 11) % 100
            if self.noise_level < 10:
                print(json.dumps({"time": self.time, "entity": "subnet", "event": "packet_get", "payload": {"behavior": "drop", "channel": self.direction, "noise_value": self.noise_level}}), file=sys.stdout, flush=True)
            else:
                print(json.dumps({"time": self.time, "entity": "subnet", "event": "packet_get", "payload": {"behavior": "pass", "channel": self.direction, "noise_value": self.noise_level}}), file=sys.stdout, flush=True)
                self.hold_in("TRANSMIT_PACKET", self.channel_delay)

    def exit(self):
        pass

class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None, total_packets: int, seed: int, timeout: float, sender_delay: float, receiver_delay: float, channel_delay: float):
        super().__init__(name)
        self.parent = parent
        self.sender = Sender(name="sender", parent=self, total_packets=total_packets, sender_delay=sender_delay, timeout=timeout)
        self.receiver = Receiver(name="receiver", parent=self, receiver_delay=receiver_delay)
        self.subnet1 = Subnet(name="subnet1", parent=self, channel_delay=channel_delay, seed=seed, direction="forward")
        self.subnet2 = Subnet(name="subnet2", parent=self, channel_delay=channel_delay, seed=seed, direction="backward")
        self.add_component(self.sender)
        self.add_component(self.receiver)
        self.add_component(self.subnet1)
        self.add_component(self.subnet2)
        self.add_coupling(self.sender.output["out_packet"], self.subnet1.input["in_packet"])
        self.add_coupling(self.subnet1.output["out_packet"], self.receiver.input["in_packet"])
        self.add_coupling(self.receiver.output["out_ack"], self.subnet2.input["in_packet"])
        self.add_coupling(self.subnet2.output["out_packet"], self.sender.input["in_ack"])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--total_packets", type=int, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--sender_delay", type=float, default=10)
    parser.add_argument("--receiver_delay", type=float, default=10)
    parser.add_argument("--channel_delay", type=float, default=3)
    parser.add_argument("--simulate_time", type=float, default=1000)
    args = parser.parse_args()

    root = System(name="system", parent=None, total_packets=args.total_packets, seed=args.seed, timeout=args.timeout, sender_delay=args.sender_delay, receiver_delay=args.receiver_delay, channel_delay=args.channel_delay)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.simulate_time)

if __name__ == "__main__":
    main()