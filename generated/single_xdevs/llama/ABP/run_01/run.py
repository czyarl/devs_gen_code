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
        self.packet_sent = False
        self.ack_received = False
        self.add_in_port(Port("ack", "ack_in"))
        self.add_out_port(Port("packet", "packet_out"))

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        if self.packet_sent:
            self.hold_in("WAIT_ACK", self.timeout)
        else:
            self.hold_in("SEND_PACKET", self.sender_delay)

    def deltext(self, e):
        if "ack_in" in e:
            ack_bit = e["ack_in"].value
            self.ack_received = True
            if ack_bit == self.bit:
                self.seq_num += 1
                self.bit = 1 - self.bit
                self.packet_sent = False
                self.ack_received = False
                if self.seq_num > self.total_packets:
                    self.exit()
                    return
            self.hold_in("WAIT_ACK", 0)
        else:
            self.hold_in("WAIT_ACK", 0)

    def exit(self):
        print(json.dumps({"time": self.time, "entity": "sender", "event": "simulation_end", "payload": {}}), file=sys.stdout, flush=True)

    def hold_in(self, phase: str, sigma: float):
        if phase == "SEND_PACKET":
            self.packet_sent = True
            print(json.dumps({"time": self.time, "entity": "sender", "event": "delay_start", "payload": {"type": "preparation", "duration": self.sender_delay}}), file=sys.stdout, flush=True)
            print(json.dumps({"time": self.time, "entity": "sender", "event": "packet_sent", "payload": {"seq_num": self.seq_num, "bit": self.bit, "is_retry": False}}), file=sys.stdout, flush=True)
            super().hold_in(phase, sigma)
        elif phase == "WAIT_ACK":
            super().hold_in(phase, sigma)
        elif phase == "INIT":
            print(json.dumps({"time": self.time, "entity": "sender", "event": "delay_start", "payload": {"type": "preparation", "duration": self.sender_delay}}), file=sys.stdout, flush=True)
            super().hold_in(phase, sigma)


class Receiver(Atomic):
    def __init__(self, name: str, parent: Coupled | None, receiver_delay: float):
        super().__init__(name)
        self.parent = parent
        self.receiver_delay = receiver_delay
        self.add_in_port(Port("packet", "packet_in"))
        self.add_out_port(Port("ack", "ack_out"))

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("PROCESS_PACKET", self.receiver_delay)

    def deltext(self, e):
        if "packet_in" in e:
            packet = e["packet_in"].value
            print(json.dumps({"time": self.time, "entity": "receiver", "event": "packet_received", "payload": {"seq_num": packet["seq_num"], "bit": packet["bit"]}}), file=sys.stdout, flush=True)
            self.hold_in("PROCESS_PACKET", self.receiver_delay)
        else:
            self.hold_in("INIT", 0)

    def exit(self):
        pass

    def hold_in(self, phase: str, sigma: float):
        if phase == "PROCESS_PACKET":
            packet = self.input["packet_in"].value
            print(json.dumps({"time": self.time, "entity": "receiver", "event": "delay_start", "payload": {"type": "processing", "duration": self.receiver_delay}}), file=sys.stdout, flush=True)
            ack_bit = packet["bit"]
            print(json.dumps({"time": self.time, "entity": "receiver", "event": "packet_sent", "payload": {"seq_num": packet["seq_num"], "bit": ack_bit}}), file=sys.stdout, flush=True)
            super().hold_in(phase, sigma)
        elif phase == "INIT":
            super().hold_in(phase, sigma)


class Subnet(Atomic):
    def __init__(self, name: str, parent: Coupled | None, channel_delay: float, seed: int, direction: str):
        super().__init__(name)
        self.parent = parent
        self.channel_delay = channel_delay
        self.seed = seed
        self.direction = direction
        self.noise_level = seed
        self.add_in_port(Port("packet", "packet_in"))
        self.add_out_port(Port("packet", "packet_out"))

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("TRANSMIT_PACKET", self.channel_delay)

    def deltext(self, e):
        if "packet_in" in e:
            packet = e["packet_in"].value
            self.noise_level = (17 * self.noise_level + 11) % 100
            if self.noise_level < 10:
                print(json.dumps({"time": self.time, "entity": "subnet", "event": "packet_get", "payload": {"behavior": "drop", "channel": self.direction, "noise_value": self.noise_level}}), file=sys.stdout, flush=True)
            else:
                print(json.dumps({"time": self.time, "entity": "subnet", "event": "packet_get", "payload": {"behavior": "pass", "channel": self.direction, "noise_value": self.noise_level}}), file=sys.stdout, flush=True)
                self.output["packet_out"].add(packet)
            self.hold_in("TRANSMIT_PACKET", self.channel_delay)
        else:
            self.hold_in("INIT", 0)

    def exit(self):
        pass

    def hold_in(self, phase: str, sigma: float):
        if phase == "TRANSMIT_PACKET":
            super().hold_in(phase, sigma)
        elif phase == "INIT":
            super().hold_in(phase, sigma)


class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None, total_packets: int, seed: int, sender_delay: float, receiver_delay: float, channel_delay: float, timeout: float, simulate_time: float):
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
        self.add_coupling(self.sender.output["packet"], self.subnet1.input["packet"])
        self.add_coupling(self.subnet1.output["packet"], self.receiver.input["packet"])
        self.add_coupling(self.receiver.output["ack"], self.subnet2.input["packet"])
        self.add_coupling(self.subnet2.output["packet"], self.sender.input["ack"])

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

    root = System(name="system", parent=None, total_packets=args.total_packets, seed=args.seed, sender_delay=args.sender_delay, receiver_delay=args.receiver_delay, channel_delay=args.channel_delay, timeout=args.timeout, simulate_time=args.simulate_time)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.simulate_time)

if __name__ == "__main__":
    main()