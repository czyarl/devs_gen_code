python
import argparse
import json
import logging
import random
import sys
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

class Sender(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("control", "in"))
        self.add_out_port(Port("packet", "out"))
        self.total_packets_to_send = 0
        self.packets_remaining = 0
        self.seq = 1
        self.bit = 0
        self.waiting_for_ack = False
        self.preparing = False

    def initialize(self):
        self.hold_in("idle", 0)

    def lambdaf(self):
        if self.preparing:
            self.output["out"].add({"type": "preparation_started", "duration": 10000})
        elif self.waiting_for_ack:
            pass
        else:
            pass

    def deltint(self):
        if self.preparing:
            self.preparing = False
            self.waiting_for_ack = True
            self.output["out"].add({"type": "packet_sent", "seq": self.seq, "bit": self.bit, "is_retry": False})
            self.hold_in("waiting_for_ack", 20000)
        elif self.waiting_for_ack:
            self.seq += 1
            self.bit = 1 - self.bit
            self.packets_remaining -= 1
            self.waiting_for_ack = False
            if self.packets_remaining > 0:
                self.preparing = True
                self.hold_in("preparing", 10000)
            else:
                self.hold_in("idle", 0)
        else:
            pass

    def deltext(self, e):
        for msg in self.input["in"].values:
            if msg["type"] == "control":
                self.total_packets_to_send += msg["added"]
                self.packets_remaining = self.total_packets_to_send
                if not self.preparing and not self.waiting_for_ack:
                    self.preparing = True
                    self.hold_in("preparing", 10000)
            else:
                pass
        self.input["in"].clear()

    def exit(self):
        pass


class ServerReceiver(Atomic):
    str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("packet", "in"))
        self.add_out_port(Port("ack", "out"))
        self.add_out_port(Port("packet", "storage"))
        self.expected_bit = 0
        self.processing = False

    def initialize(self):
        self.hold_in("idle", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        if self.processing:
            self.processing = False
            packet = self.parent.storage_queue.pop(0)
            self.output["storage"].add(packet)
            self.output["out"].add({"type": "ack_sent_to_sender", "bit": self.expected_bit})
            self.expected_bit = 1 - self.expected_bit
            self.hold_in("idle", 0)
        else:
            pass

    def deltext(self, e):
        for msg in self.input["in"].values:
            if msg["type"] == "packet":
                self.processing = True
                self.hold_in("processing", 3000)
                self.output["in"].add({"type": "packet_received", "seq": msg["seq"], "bit": msg["bit"]})
        self.input["in"].clear()

    def exit(self):
        pass


class ServerSender(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("packet", "in"))
        self.add_out_port(Port("packet", "out"))
        self.download_allowed = False
        self.waiting_for_ack = False
        self.bit = 0

    def initialize(self):
        self.hold_in("idle", 0)

    def lambdaf(self):
        if self.parent.storage_queue and self.download_allowed and not self.waiting_for_ack:
            packet = self.parent.storage_queue[0]
            self.output["out"].add(packet)
            self.waiting_for_ack = True
            self.bit = packet["bit"]
            self.hold_in("waiting_for_ack", 0)

    def deltint(self):
        if self.waiting_for_ack:
            pass
        else:
            pass

    def deltext(self, e):
        for msg in self.input["in"].values:
            if msg["type"] == "download_valve_change":
                self.download_allowed = msg["allowed"]
            elif msg["type"] == "ack":
                self.waiting_for_ack = False
                self.hold_in("idle", 0)
        self.input["in"].clear()

    def exit(self):
        pass


class Receiver(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("packet", "in"))
        self.add_out_port(Port("ack", "out"))

    def initialize(self):
        self.hold_in("idle", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        for msg in self.input["in"].values:
            self.output["out"].add({"type": "ack_sent", "bit": msg["bit"]})
            self.hold_in("processing", 10000)
        self.input["in"].clear()

    def exit(self):
        pass


class Subnet(Atomic):
    def __init__(self, name: str, parent: Coupled | None, delay):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("packet", "in"))
        self.add_out_port(Port("packet", "out"))
        self.delay = delay

    def initialize(self):
        self.hold_in("idle", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        for msg in self.input["in"].values:
            self.hold_in("transmitting", self.delay)
            self.output["out"].add(msg)
        self.input["in"].clear()

    def exit(self):
        pass


class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None, simulation_time):
        super().__init__(name)
        self.parent = parent
        self.storage_queue = []
        self.sender = Sender(name="sender", parent=self)
        self.server_receiver = ServerReceiver(name="server_receiver", parent=self)
        self.server_sender = ServerSender(name="server_sender", parent=self)
        self.receiver = Receiver(name="receiver", parent=self)
        self.subnet_a1 = Subnet(name="subnet_a1", parent=self, delay=3000)
        self.subnet_a2 = Subnet(name="subnet_a2", parent=self, delay=3000)
        self.subnet_b1 = Subnet(name="subnet_b1", parent=self, delay=3000)
        self.subnet_b2 = Subnet(name="subnet_b2", parent=self, delay=3000)
        self.add_component(self.sender)
        self.add_component(self.server_receiver)
        self.add_component(self.server_sender)
        self.add_component(self.receiver)
        self.add_component(self.subnet_a1)
        self.add_component(self.subnet_a2)
        self.add_component(self.subnet_b1)
        self.add_component(self.subnet_b2)
        self.add_coupling(self.sender.output["out"], self.subnet_a1.input["in"])
        self.add_coupling(self.subnet_a1.output["out"], self.server_receiver.input["in"])
        self.add_coupling(self.server_receiver.output["storage"], self.server_sender.input["in"])
        self.add_coupling(self.server_sender.output["out"], self.subnet_b1.input["in"])
        self.add_coupling(self.subnet_b1.output["out"], self.receiver.input["in"])
        self.add_coupling(self.receiver.output["out"], self.subnet_b2.input["in"])
        self.add_coupling(self.subnet_b2.output["out"], self.server_sender.input["in"])
        self.add_coupling(self.input["control"], self.sender.input["in"])
        self.add_coupling(self.input["request"], self.server_sender.input["in"])

    def __init__(self, name: str, parent: Coupled | None, simulation_time):
        super().__init__(name)
        self.parent = parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=10000_000.0)
    args = parser.parse_args()

    root = System(name="system", parent=None, simulation_time=args.simulation_time)

    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.simulation_time)

    for line in sys.stdin:
        try:
            time, type, value = line.strip().split()
            if type == "control":
                root.sender.input["in"].add({"type": "control", "added": int(value)})
            elif type == "request":
                root.server_sender.input["in"].add({"type": "download_valve_change", "allowed": bool(int(value))})
        except Exception as e:
            logging.error(f"Error processing input: {e}")

if __name__ == "__main__":
    main()
```