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
        self.seq_num = 1
        self.bit = 0
        self.timer_active = False
        self.packet_sent = False

        self.add_out_port(Port("packet", "out"))

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        if not self.timer_active:
            self.hold_in("WAIT", self.sender_delay)
            self.output["out"].add({"seq_num": self.seq_num, "bit": self.bit, "is_retry": False})
            print(json.dumps({"time": self.time, "entity": "sender", "event": "delay_start", "payload": {"type": "preparation", "duration": self.sender_delay}}), file=sys.stdout, flush=True)
            print(json.dumps({"time": self.time, "entity": "sender", "event": "packet_sent", "payload": {"seq_num": self.seq_num, "bit": self.bit, "is_retry": False}}), file=sys.stdout, flush=True)
            self.packet_sent = True
            self.timer_active = True
            self.hold_in("WAIT_ACK", self.timeout)
        else:
            self.seq_num += 1
            self.bit = 1 - self.bit
            self.packet_sent = False
            self.timer_active = False
            self.hold_in("INIT", 0)

    def deltext(self, e):
        if "ack" in e:
            ack_bit = e["ack"]["bit"]
            is_valid = ack_bit == self.bit
            print(json.dumps({"time": self.time, "entity": "sender", "event": "ack_received", "payload": {"ack_bit": ack_bit, "is_valid": is_valid}}), file=sys.stdout, flush=True)
            if is_valid:
                self.timer_active = False
                self.hold_in("INIT", 0)

    def exit(self):
        pass

class Receiver(Atomic):
    def __init__(self, name: str, parent: Coupled | None, receiver_delay: float):
        super().__init__(name)
        self.parent = parent
        self.receiver_delay = receiver_delay
        self.add_in_port(Port("packet", "in"))
        self.add_out_port(Port("ack", "out"))

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        if "packet" in e:
            packet = e["packet"]
            print(json.dumps({"time": self.time, "entity": "receiver", "event": "delay_start", "payload": {"type": "processing", "duration": self.receiver_delay}}), file=sys.stdout, flush=True)
            self.hold_in("PROCESSING", self.receiver_delay)
            seq_num = packet["seq_num"]
            bit = packet["bit"]
            print(json.dumps({"time": self.time, "entity": "receiver", "event": "packet_received", "payload": {"seq_num": seq_num, "bit": bit}}), file=sys.stdout, flush=True)
            self.output["out"].add({"bit": bit})

    def exit(self):
        pass

class Subnet(Atomic):
    def __init__(self, name: str, parent: Coupled | None, channel_delay: float, seed: int, direction: str):
        super().__init__(name)
        self.parent = parent
        self.channel_delay = channel_delay
        self.seed = seed
        self.noise_level = seed
        self.direction = direction
        self.add_in_port(Port("packet", "in"))
        self.add_out_port(Port("packet", "out"))

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        if "packet" in e:
            packet = e["packet"]
            self.noise_level = (17 * self.noise_level + 11) % 100
            if self.noise_level < 10:
                print(json.dumps({"time": self.time, "entity": "subnet", "event": "packet_get", "payload": {"behavior": "drop", "channel": self.direction, "noise_value": self.noise_level}}), file=sys.stdout, flush=True)
            else:
                print(json.dumps({"time": self.time, "entity": "subnet", "event": "packet_get", "payload": {"behavior": "pass", "channel": self.direction, "noise_value": self.noise_level}}), file=sys.stdout, flush=True)
                self.output["out"].add(packet)
                self.hold_in("WAIT", self.channel_delay)

    def exit(self):
        pass

class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None, total_packets: int, seed: int, timeout: float, sender_delay: float, receiver_delay: float, channel_delay: float, simulate_time: float):
        super().__init__(name)
        self.parent = parent

        self.sender = Sender(name="sender", parent=self, total_packets=total_packets, sender_delay=sender_delay, timeout=timeout)
        self.add_component(self.sender)

        self.receiver = Receiver(name="receiver", parent=self, receiver_delay=receiver_delay)
        self.add_component(self.receiver)

        self.subnet1 = Subnet(name="subnet1", parent=self, channel_delay=channel_delay, seed=seed, direction="forward")
        self.add_component(self.subnet1)

        self.subnet2 = Subnet(name="subnet2", parent=self, channel_delay=channel_delay, seed=seed, direction="backward")
        self.add_component(self.subnet2)

        self.add_coupling(self.sender.output["out"], self.subnet1.input["in"])
        self.add_coupling(self.subnet1.output["out"], self.receiver.input["in"])
        self.add_coupling(self.receiver.output["out"], self.subnet2.input["in"])
        self.add_coupling(self.subnet2.output["out"], self.sender.input["ack"])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--total_packets", type=int, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--sender_delay", type=float, default=10)
    parser.add_argument("--receiver_delay", type=float, default=10)
    parser.add_argument("--channel_delay", type=float, default=3)
    parser.add_argument("--simulate_time", type=float, required=True)
    args = parser.parse_args()

    root = System(name="system", parent=None, total_packets=args.total_packets, seed=args.seed, timeout=args.timeout, sender_delay=args.sender_delay, receiver_delay=args.receiver_delay, channel_delay=args.channel_delay, simulate_time=args.simulate_time)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.simulate_time)

if __name__ == "__main__":
    main()