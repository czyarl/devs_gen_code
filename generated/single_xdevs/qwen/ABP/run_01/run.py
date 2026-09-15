import argparse
import sys
import json
import random
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

class Sender(Atomic):
    def __init__(self, name: str, parent: Coupled | None, total_packets: int, seed: int, timeout: int, sender_delay: int):
        super().__init__(name)
        self.parent = parent
        self.total_packets = total_packets
        self.timeout = timeout
        self.sender_delay = sender_delay
        self.seed = seed
        self.current_seq = 1
        self.current_bit = 0
        self.timer = None
        self.packet_buffer = deque()
        self.retransmit_count = 0
        self.is_retransmit = False

        # Ports
        self.in_ack = Port(dict, "in_ack")
        self.out_packet = Port(dict, "out_packet")
        self.out_timeout = Port(float, "out_timeout")
        self.add_in_port(self.in_ack)
        self.add_out_port(self.out_packet)
        self.add_out_port(self.out_timeout)

        self.hold_in("INIT", 0)

    def initialize(self):
        self.hold_in("WAITING", 0)

    def lambdaf(self):
        if self.phase == "SENDING":
            self.output["out_packet"].add({
                "seq_num": self.current_seq,
                "bit": self.current_bit,
                "is_retry": self.is_retransmit
            })

    def deltint(self):
        if self.phase == "INIT":
            self.hold_in("WAITING", 0)
        elif self.phase == "WAITING":
            self.hold_in("PREPARING", self.sender_delay)
        elif self.phase == "PREPARING":
            self.hold_in("SENDING", 0)
        elif self.phase == "SENDING":
            self.hold_in("WAITING_ACK", self.timeout)
        elif self.phase == "WAITING_ACK":
            # Timeout occurred
            self.retransmit_count += 1
            self.is_retransmit = True
            self.current_seq = self.current_seq  # Retransmit same packet
            self.hold_in("SENDING", 0)
        elif self.phase == "DONE":
            self.hold_in("DONE", float('inf'))

    def deltext(self, e):
        if self.phase == "WAITING":
            # Start sending first packet
            self.hold_in("PREPARING", 0)
        elif self.phase == "WAITING_ACK":
            # Received ACK
            ack_data = self.input["in_ack"].values[0]
            ack_bit = ack_data["ack_bit"]
            is_valid = ack_data["is_valid"]
            if is_valid:
                # Valid ACK received
                self.current_seq += 1
                self.current_bit = 1 - self.current_bit  # Flip bit
                self.retransmit_count = 0
                self.is_retransmit = False
                if self.current_seq > self.total_packets:
                    self.hold_in("DONE", 0)
                else:
                    self.hold_in("WAITING", 0)
            else:
                # Invalid ACK, retransmit
                self.hold_in("SENDING", 0)
        elif self.phase == "DONE":
            pass

    def exit(self):
        pass

class Receiver(Atomic):
    def __init__(self, name: str, parent: Coupled | None, seed: int, receiver_delay: int):
        super().__init__(name)
        self.parent = parent
        self.seed = seed
        self.receiver_delay = receiver_delay
        self.current_bit = None
        self.packet_buffer = deque()

        # Ports
        self.in_packet = Port(dict, "in_packet")
        self.out_ack = Port(dict, "out_ack")
        self.add_in_port(self.in_packet)
        self.add_out_port(self.out_ack)

        self.hold_in("INIT", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.phase == "PROCESSING":
            if self.packet_buffer:
                packet = self.packet_buffer.popleft()
                ack_bit = packet["bit"]
                self.output["out_ack"].add({
                    "ack_bit": ack_bit,
                    "is_valid": True
                })

    def deltint(self):
        if self.phase == "INIT":
            self.hold_in("IDLE", 0)
        elif self.phase == "IDLE":
            self.hold_in("PROCESSING", self.receiver_delay)
        elif self.phase == "PROCESSING":
            self.hold_in("IDLE", 0)

    def deltext(self, e):
        if self.phase == "IDLE":
            packet_data = self.input["in_packet"].values[0]
            self.packet_buffer.append(packet_data)
            self.hold_in("PROCESSING", 0)
        elif self.phase == "PROCESSING":
            pass

    def exit(self):
        pass

class Subnet(Atomic):
    def __init__(self, name: str, parent: Coupled | None, seed: int, channel_delay: int, direction: str):
        super().__init__(name)
        self.parent = parent
        self.seed = seed
        self.channel_delay = channel_delay
        self.direction = direction
        self.noise_level = seed
        self.packet_buffer = deque()

        # Ports
        self.in_packet = Port(dict, "in_packet")
        self.out_packet = Port(dict, "out_packet")
        self.add_in_port(self.in_packet)
        self.add_out_port(self.out_packet)

        self.hold_in("INIT", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.phase == "TRANSITING":
            if self.packet_buffer:
                packet = self.packet_buffer.popleft()
                self.output["out_packet"].add(packet)

    def deltint(self):
        if self.phase == "INIT":
            self.hold_in("IDLE", 0)
        elif self.phase == "IDLE":
            self.hold_in("TRANSITING", self.channel_delay)
        elif self.phase == "TRANSITING":
            self.hold_in("IDLE", 0)

    def deltext(self, e):
        if self.phase == "IDLE":
            packet_data = self.input["in_packet"].values[0]
            # Determine fate of packet
            new_noise_level = (17 * self.noise_level + 11) % 100
            self.noise_level = new_noise_level
            if new_noise_level < 10:
                # Drop packet
                self.output["out_packet"].add({
                    "behavior": "drop",
                    "channel": self.direction,
                    "noise_value": new_noise_level
                })
            else:
                # Pass packet
                self.packet_buffer.append({
                    "behavior": "pass",
                    "channel": self.direction,
                    "noise_value": new_noise_level,
                    "data": packet_data
                })
                self.hold_in("TRANSITING", 0)
        elif self.phase == "TRANSITING":
            pass

    def exit(self):
        pass

class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None, total_packets: int, seed: int, timeout: int, sender_delay: int, receiver_delay: int, channel_delay: int):
        super().__init__(name)
        self.parent = parent

        # Instantiate sub-models
        self.sender = Sender(name="sender", parent=self, total_packets=total_packets, seed=seed, timeout=timeout, sender_delay=sender_delay)
        self.receiver = Receiver(name="receiver", parent=self, seed=seed, receiver_delay=receiver_delay)
        self.subnet1 = Subnet(name="subnet1", parent=self, seed=seed, channel_delay=channel_delay, direction="forward")
        self.subnet2 = Subnet(name="subnet2", parent=self, seed=seed, channel_delay=channel_delay, direction="backward")

        self.add_component(self.sender)
        self.add_component(self.receiver)
        self.add_component(self.subnet1)
        self.add_component(self.subnet2)

        # Define couplings
        # Sender to Subnet1
        self.add_coupling(self.sender.out_packet, self.subnet1.in_packet)
        # Subnet1 to Receiver
        self.add_coupling(self.subnet1.out_packet, self.receiver.in_packet)
        # Receiver to Subnet2
        self.add_coupling(self.receiver.out_ack, self.subnet2.in_packet)
        # Subnet2 to Sender
        self.add_coupling(self.subnet2.out_packet, self.sender.in_ack)

        # Add timing coupling
        self.add_coupling(self.sender.out_timeout, self.subnet1.in_packet)

    def initialize(self):
        pass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--total_packets", type=int, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--sender_delay", type=int, default=10)
    parser.add_argument("--receiver_delay", type=int, default=10)
    parser.add_argument("--channel_delay", type=int, default=3)
    parser.add_argument("--simulate_time", type=int, default=1000)
    args = parser.parse_args()

    root = System(
        name="system",
        parent=None,
        total_packets=args.total_packets,
        seed=args.seed,
        timeout=args.timeout,
        sender_delay=args.sender_delay,
        receiver_delay=args.receiver_delay,
        channel_delay=args.channel_delay
    )
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.simulate_time)

if __name__ == "__main__":
    main()