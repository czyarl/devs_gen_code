import argparse
import sys
import json
import random
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

class Sender(Atomic):
    def __init__(self, name, parent, total_packets, seed, timeout, sender_delay):
        super().__init__(name)
        self.parent = parent
        self.total_packets = total_packets
        self.timeout = timeout
        self.sender_delay = sender_delay
        self.seq_num = 1
        self.bit = 0
        self.packet_sent = False
        self.timer_active = False
        self.retransmit_count = 0
        self.noise_level = seed
        self.packet_buffer = None

        self.in_port = Port(dict, "in_port")
        self.out_port = Port(dict, "out_port")
        self.add_in_port(self.in_port)
        self.add_out_port(self.out_port)

        self.hold_in("INIT", 0)

    def initialize(self):
        self.hold_in("WAIT_FOR_PACKET", 0)

    def lambdaf(self):
        if self.phase == "SEND_PACKET":
            packet = {
                "seq_num": self.seq_num,
                "bit": self.bit,
                "is_retry": self.retransmit_count > 0
            }
            self.out_port.add(packet)
            self.log_event("packet_sent", packet)

    def deltint(self):
        if self.phase == "INIT":
            self.hold_in("WAIT_FOR_PACKET", 0)
        elif self.phase == "WAIT_FOR_PACKET":
            self.hold_in("PREPARE_PACKET", self.sender_delay)
        elif self.phase == "PREPARE_PACKET":
            self.hold_in("SEND_PACKET", 0)
        elif self.phase == "SEND_PACKET":
            self.packet_sent = True
            self.timer_active = True
            self.hold_in("WAIT_FOR_ACK", self.timeout)
        elif self.phase == "WAIT_FOR_ACK":
            self.hold_in("SEND_PACKET", 0)
        elif self.phase == "RECEIVE_ACK":
            self.hold_in("WAIT_FOR_PACKET", 0)

    def deltext(self, e):
        if self.phase == "WAIT_FOR_PACKET":
            if self.input["in_port"].values:
                self.hold_in("PREPARE_PACKET", self.sender_delay)
        elif self.phase == "WAIT_FOR_ACK":
            if self.input["in_port"].values:
                ack = self.input["in_port"].values[0]
                ack_bit = ack["ack_bit"]
                is_valid = ack["is_valid"]
                self.log_event("ack_received", {"ack_bit": ack_bit, "is_valid": is_valid})
                if is_valid:
                    self.seq_num += 1
                    self.bit = 1 - self.bit  # Toggle bit
                    self.timer_active = False
                    self.retransmit_count = 0
                    self.hold_in("WAIT_FOR_PACKET", 0)
                else:
                    self.retransmit_count += 1
                    self.hold_in("SEND_PACKET", 0)
        elif self.phase == "SEND_PACKET":
            self.hold_in("WAIT_FOR_ACK", self.timeout)
        elif self.phase == "RECEIVE_ACK":
            self.hold_in("WAIT_FOR_PACKET", 0)

    def exit(self):
        pass

    def log_event(self, event, payload):
        print(json.dumps({
            "time": self.time,
            "entity": "sender",
            "event": event,
            "payload": payload
        }), file=sys.stdout, flush=True)

class Receiver(Atomic):
    def __init__(self, name, parent, receiver_delay):
        super().__init__(name)
        self.parent = parent
        self.receiver_delay = receiver_delay
        self.seq_num = 1
        self.bit = 0

        self.in_port = Port(dict, "in_port")
        self.out_port = Port(dict, "out_port")
        self.add_in_port(self.in_port)
        self.add_out_port(self.out_port)

        self.hold_in("INIT", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.phase == "PROCESS_PACKET":
            ack = {
                "ack_bit": self.bit
            }
            self.out_port.add(ack)
            self.log_event("packet_received", {"seq_num": self.seq_num, "bit": self.bit})

    def deltint(self):
        if self.phase == "INIT":
            self.hold_in("IDLE", 0)
        elif self.phase == "IDLE":
            self.hold_in("PROCESS_PACKET", 0)
        elif self.phase == "PROCESS_PACKET":
            self.hold_in("IDLE", 0)

    def deltext(self, e):
        if self.phase == "IDLE":
            if self.input["in_port"].values:
                packet = self.input["in_port"].values[0]
                self.seq_num = packet["seq_num"]
                self.bit = packet["bit"]
                self.log_event("delay_start", {"type": "processing", "duration": self.receiver_delay})
                self.hold_in("PROCESS_PACKET", self.receiver_delay)
        elif self.phase == "PROCESS_PACKET":
            self.hold_in("IDLE", 0)

    def exit(self):
        pass

    def log_event(self, event, payload):
        print(json.dumps({
            "time": self.time,
            "entity": "receiver",
            "event": event,
            "payload": payload
        }), file=sys.stdout, flush=True)

class Subnet(Atomic):
    def __init__(self, name, parent, channel_delay, seed, channel_type):
        super().__init__(name)
        self.parent = parent
        self.channel_delay = channel_delay
        self.noise_level = seed
        self.channel_type = channel_type  # "forward" or "backward"

        self.in_port = Port(dict, "in_port")
        self.out_port = Port(dict, "out_port")
        self.add_in_port(self.in_port)
        self.add_out_port(self.out_port)

        self.hold_in("INIT", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.phase == "TRANSMIT_PACKET":
            packet = self.input["in_port"].values[0]
            self.out_port.add(packet)

    def deltint(self):
        if self.phase == "INIT":
            self.hold_in("IDLE", 0)
        elif self.phase == "IDLE":
            self.hold_in("TRANSMIT_PACKET", self.channel_delay)
        elif self.phase == "TRANSMIT_PACKET":
            self.hold_in("IDLE", 0)

    def deltext(self, e):
        if self.phase == "IDLE":
            if self.input["in_port"].values:
                packet = self.input["in_port"].values[0]
                # Calculate new noise level
                self.noise_level = (17 * self.noise_level + 11) % 100
                # Determine fate
                if self.noise_level < 10:
                    # Drop packet
                    self.log_event("packet_get", {
                        "behavior": "drop",
                        "channel": self.channel_type,
                        "noise_value": self.noise_level
                    })
                    self.hold_in("IDLE", 0)
                else:
                    # Pass packet
                    self.log_event("packet_get", {
                        "behavior": "pass",
                        "channel": self.channel_type,
                        "noise_value": self.noise_level
                    })
                    self.hold_in("TRANSMIT_PACKET", self.channel_delay)

    def exit(self):
        pass

    def log_event(self, event, payload):
        print(json.dumps({
            "time": self.time,
            "entity": "subnet",
            "event": event,
            "payload": payload
        }), file=sys.stdout, flush=True)

class System(Coupled):
    def __init__(self, name, parent, total_packets, seed, timeout, sender_delay, receiver_delay, channel_delay):
        super().__init__(name)
        self.parent = parent

        # Create components
        self.sender = Sender("sender", self, total_packets, seed, timeout, sender_delay)
        self.receiver = Receiver("receiver", self, receiver_delay)
        self.forward_subnet = Subnet("forward_subnet", self, channel_delay, seed, "forward")
        self.backward_subnet = Subnet("backward_subnet", self, channel_delay, seed, "backward")

        self.add_component(self.sender)
        self.add_component(self.receiver)
        self.add_component(self.forward_subnet)
        self.add_component(self.backward_subnet)

        # Define couplings
        # Sender -> Forward Subnet
        self.add_coupling(self.sender.out_port, self.forward_subnet.in_port)
        # Forward Subnet -> Receiver
        self.add_coupling(self.forward_subnet.out_port, self.receiver.in_port)
        # Receiver -> Backward Subnet
        self.add_coupling(self.receiver.out_port, self.backward_subnet.in_port)
        # Backward Subnet -> Sender
        self.add_coupling(self.backward_subnet.out_port, self.sender.in_port)

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