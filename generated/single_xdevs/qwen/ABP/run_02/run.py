import argparse
import sys
import json
import random
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Global constants
MS = 1.0  # Time unit: 1ms = 1.0 simulation time unit

class Packet:
    def __init__(self, seq_num, bit):
        self.seq_num = seq_num
        self.bit = bit

class AckPacket:
    def __init__(self, ack_bit):
        self.ack_bit = ack_bit

class Sender(Atomic):
    def __init__(self, name, parent, total_packets, sender_delay, timeout):
        super().__init__(name)
        self.parent = parent
        self.total_packets = total_packets
        self.sender_delay = sender_delay
        self.timeout = timeout
        self.packet_count = 0
        self.current_bit = 0
        self.timer_active = False
        self.waiting_for_ack = False
        self.last_sent_packet = None
        self.retransmit_count = 0
        
        # Ports
        self.in_port_ack = Port(AckPacket, "in_port_ack")
        self.out_port_packet = Port(Packet, "out_port_packet")
        self.add_in_port(self.in_port_ack)
        self.add_out_port(self.out_port_packet)
        
        # Initialize
        self.hold_in("IDLE", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        # Only output when sending packet
        if self.phase == "SENDING":
            self.output["out_port_packet"].add(self.last_sent_packet)

    def deltint(self):
        if self.phase == "IDLE":
            if self.packet_count < self.total_packets:
                self.hold_in("PREPARE", self.sender_delay)
            else:
                self.hold_in("DONE", 0)
        elif self.phase == "PREPARE":
            self.packet_count += 1
            packet = Packet(self.packet_count, self.current_bit)
            self.last_sent_packet = packet
            self.waiting_for_ack = True
            self.timer_active = True
            self.hold_in("SENDING", 0)
        elif self.phase == "SENDING":
            self.current_bit = 1 - self.current_bit  # Alternate bit
            self.hold_in("WAITING", self.timeout)
        elif self.phase == "WAITING":
            # Timeout occurred
            self.retransmit_count += 1
            self.timer_active = False
            self.waiting_for_ack = False
            self.hold_in("PREPARE", 0)  # Retransmit immediately
        elif self.phase == "DONE":
            self.hold_in("DONE", 0)

    def deltext(self, e):
        if self.phase == "WAITING":
            ack = self.input["in_port_ack"].values[0]
            if ack.ack_bit == self.last_sent_packet.bit:
                # Valid ACK received
                self.timer_active = False
                self.waiting_for_ack = False
                self.hold_in("IDLE", 0)
            else:
                # Invalid ACK - retransmit
                self.hold_in("PREPARE", 0)
        else:
            self.hold_in(self.phase, 0)

    def exit(self):
        pass

class Receiver(Atomic):
    def __init__(self, name, parent, receiver_delay):
        super().__init__(name)
        self.parent = parent
        self.receiver_delay = receiver_delay
        self.processing_active = False
        self.buffer = None  # Only buffer one packet
        
        # Ports
        self.in_port_packet = Port(Packet, "in_port_packet")
        self.out_port_ack = Port(AckPacket, "out_port_ack")
        self.add_in_port(self.in_port_packet)
        self.add_out_port(self.out_port_ack)
        
        # Initialize
        self.hold_in("IDLE", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.phase == "PROCESSING":
            ack = AckPacket(self.buffer.bit)
            self.output["out_port_ack"].add(ack)

    def deltint(self):
        if self.phase == "IDLE":
            self.hold_in("IDLE", 0)
        elif self.phase == "PROCESSING":
            self.processing_active = False
            self.hold_in("IDLE", 0)

    def deltext(self, e):
        if self.phase == "IDLE":
            self.buffer = self.input["in_port_packet"].values[0]
            self.processing_active = True
            self.hold_in("PROCESSING", self.receiver_delay)
        elif self.phase == "PROCESSING":
            self.buffer = self.input["in_port_packet"].values[0]
            self.hold_in("PROCESSING", self.receiver_delay)
        else:
            self.hold_in(self.phase, 0)

    def exit(self):
        pass

class Subnet(Atomic):
    def __init__(self, name, parent, channel_delay, seed, direction):
        super().__init__(name)
        self.parent = parent
        self.channel_delay = channel_delay
        self.seed = seed
        self.direction = direction  # "forward" or "backward"
        self.noise_level = seed
        self.buffer = None
        
        # Ports
        self.in_port_packet = Port(Packet, "in_port_packet")
        self.out_port_packet = Port(Packet, "out_port_packet")
        self.add_in_port(self.in_port_packet)
        self.add_out_port(self.out_port_packet)
        
        # Initialize
        self.hold_in("IDLE", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.phase == "TRANSMITTING":
            if self.buffer is not None:
                self.output["out_port_packet"].add(self.buffer)

    def deltint(self):
        if self.phase == "IDLE":
            self.hold_in("IDLE", 0)
        elif self.phase == "TRANSMITTING":
            self.buffer = None
            self.hold_in("IDLE", 0)

    def deltext(self, e):
        if self.phase == "IDLE":
            packet = self.input["in_port_packet"].values[0]
            # Determine fate based on noise level
            new_noise_level = (17 * self.noise_level + 11) % 100
            self.noise_level = new_noise_level
            if new_noise_level < 10:
                # Drop packet
                self.hold_in("IDLE", 0)
                # Log packet drop
                event = {
                    "time": self.time,
                    "entity": "subnet",
                    "event": "packet_get",
                    "payload": {
                        "behavior": "drop",
                        "channel": self.direction,
                        "noise_value": new_noise_level
                    }
                }
                print(json.dumps(event), file=sys.stdout, flush=True)
            else:
                # Pass packet
                self.buffer = packet
                self.hold_in("TRANSMITTING", self.channel_delay)
                # Log packet pass
                event = {
                    "time": self.time,
                    "entity": "subnet",
                    "event": "packet_get",
                    "payload": {
                        "behavior": "pass",
                        "channel": self.direction,
                        "noise_value": new_noise_level
                    }
                }
                print(json.dumps(event), file=sys.stdout, flush=True)
        else:
            self.hold_in(self.phase, 0)

    def exit(self):
        pass

class System(Coupled):
    def __init__(self, name, parent, total_packets, seed, timeout, sender_delay, receiver_delay, channel_delay):
        super().__init__(name)
        self.parent = parent
        
        # Instantiate components
        self.sender = Sender("sender", self, total_packets, sender_delay, timeout)
        self.receiver = Receiver("receiver", self, receiver_delay)
        self.subnet1 = Subnet("subnet1", self, channel_delay, seed, "forward")
        self.subnet2 = Subnet("subnet2", self, channel_delay, seed, "backward")
        
        self.add_component(self.sender)
        self.add_component(self.receiver)
        self.add_component(self.subnet1)
        self.add_component(self.subnet2)
        
        # Define couplings
        # Sender to Subnet1
        self.add_coupling(self.sender.out_port_packet, self.subnet1.in_port_packet)
        # Subnet1 to Receiver
        self.add_coupling(self.subnet1.out_port_packet, self.receiver.in_port_packet)
        # Receiver to Subnet2
        self.add_coupling(self.receiver.out_port_ack, self.subnet2.in_port_packet)
        # Subnet2 to Sender
        self.add_coupling(self.subnet2.out_port_packet, self.sender.in_port_ack)

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

    # Create the system
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

    # Create coordinator and run simulation
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.simulate_time)

if __name__ == "__main__":
    main()