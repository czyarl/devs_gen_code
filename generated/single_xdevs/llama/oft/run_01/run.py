import argparse
import json
import logging
import random
import sys
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

class Sender(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("control", "control_in"))
        self.add_out_port(Port("packet", "packet_out"))
        self.add_out_port(Port("ack", "ack_in"))
        self.packets_to_send = 0
        self.seq = 1
        self.bit = 0
        self.preparing = False
        self.sending = False
        self.waiting_ack = False

    def initialize(self):
        self.hold_in("idle", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        if self.phase == "preparing":
            self.preparing = False
            self.sending = True
            self.waiting_ack = True
            self.output["packet_out"].add({"seq": self.seq, "bit": self.bit, "is_retry": False})
            self.hold_in("waiting_ack", 20)
        elif self.phase == "waiting_ack":
            if self.waiting_ack:
                self.output["packet_out"].add({"seq": self.seq, "bit": self.bit, "is_retry": True})
                self.hold_in("waiting_ack", 20)
            else:
                self.hold_in("idle", 0)
        elif self.phase == "idle":
            if self.packets_to_send > 0:
                self.preparing = True
                self.hold_in("preparing", 10)

    def deltext(self, e):
        if self.input["control_in"].values:
            control_cmd = self.input["control_in"].values[0]
            self.packets_to_send += control_cmd["added"]
            self.seq = 1
            self.bit = 0
            self.waiting_ack = False
            self.hold_in("idle", 0)
            print(json.dumps({
                "timestamp_ms": self.time_ms(),
                "model": "sender",
                "type": "control_cmd",
                "val": {"added": control_cmd["added"], "total_remaining": self.packets_to_send}
            }), file=sys.stdout, flush=True)

    def exit(self):
        pass


class ServerReceiver(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("packet", "packet_in"))
        self.add_out_port(Port("ack", "ack_out"))
        self.add_out_port(Port("packet", "packet_out"))
        self.expected_bit = 0
        self.storage_queue = deque()

    def initialize(self):
        self.hold_in("idle", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        if self.phase == "processing":
            self.storage_queue.append({"seq": self.packet["seq"], "bit": self.packet["bit"]})
            self.output["ack_out"].add({"bit": self.packet["bit"]})
            self.expected_bit = 1 - self.packet["bit"]
            self.hold_in("idle", 0)

    def deltext(self, e):
        if self.input["packet_in"].values:
            self.packet = self.input["packet_in"].values[0]
            if self.packet["bit"] == self.expected_bit:
                self.hold_in("processing", 3)
            else:
                self.output["ack_out"].add({"bit": self.expected_bit})
                self.hold_in("idle", 0)
            print(json.dumps({
                "timestamp_ms": self.time_ms(),
                "model": "server_receiver",
                "type": "packet_received",
                "val": {"seq": self.packet["seq"], "bit": self.packet["bit"]}
            }), file=sys.stdout, flush=True)

    def exit(self):
        pass


class ServerSender(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("packet", "packet_in"))
        self.add_in_port(Port("request", "request_in"))
        self.add_out_port(Port("packet", "packet_out"))
        self.add_out_port(Port("ack", "ack_in"))
        self.storage_queue = deque()
        self.download_allowed = False
        self.waiting_ack = False

    def initialize(self):
        self.hold_in("idle", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        if self.phase == "sending":
            if self.storage_queue:
                packet = self.storage_queue.popleft()
                self.output["packet_out"].add(packet)
                self.waiting_ack = True
                self.hold_in("waiting_ack", 0)
            else:
                self.hold_in("idle", 0)
        elif self.phase == "waiting_ack":
            self.hold_in("idle", 0)

    def deltext(self, e):
        if self.input["request_in"].values:
            request_cmd = self.input["request_in"].values[0]
            self.download_allowed = request_cmd["allowed"]
            print(json.dumps({
                "timestamp_ms": self.time_ms(),
                "model": "server_sender",
                "type": "download_valve_change",
                "val": {"allowed": request_cmd["allowed"]}
            }), file=sys.stdout, flush=True)
        if self.input["packet_in"].values:
            packet = self.input["packet_in"].values[0]
            self.storage_queue.append(packet)
            self.hold_in("idle", 0)
        if self.download_allowed and self.storage_queue:
            self.hold_in("sending", 0)

    def exit(self):
        pass


class Receiver(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("packet", "packet_in"))
        self.add_out_port(Port("ack", "ack_out"))

    def initialize(self):
        self.hold_in("idle", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        if self.phase == "processing":
            self.output["ack_out"].add({"bit": self.packet["bit"]})
            print(json.dumps({
                "timestamp_ms": self.time_ms(),
                "model": "receiver",
                "type": "ack_sent",
                "val": {"bit": self.packet["bit"]}
            }), file=sys.stdout, flush=True)
            self.hold_in("idle", 0)

    def deltext(self, e):
        if self.input["packet_in"].values:
            self.packet = self.input["packet_in"].values[0]
            self.hold_in("processing", 10)

    def exit(self):
        pass


class Subnet(Atomic):
    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("packet", "packet_in"))
        self.add_out_port(Port("packet", "packet_out"))
        self.delay = delay

    def initialize(self):
        self.hold_in("idle", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        if self.phase == "transmitting":
            self.output["packet_out"].add(self.packet)
            self.hold_in("idle", 0)

    def deltext(self, e):
        if self.input["packet_in"].values:
            self.packet = self.input["packet_in"].values[0]
            self.hold_in("transmitting", self.delay)

    def exit(self):
        pass


class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.sender = Sender(name="sender", parent=self)
        self.server_receiver = ServerReceiver(name="server_receiver", parent=self)
        self.server_sender = ServerSender(name="server_sender", parent=self)
        self.receiver = Receiver(name="receiver", parent=self)
        self.subnet_a1 = Subnet(name="subnet_a1", parent=self, delay=3)
        self.subnet_a2 = Subnet(name="subnet_a2", parent=self, delay=3)
        self.subnet_b1 = Subnet(name="subnet_b1", parent=self, delay=3)
        self.subnet_b2 = Subnet(name="subnet_b2", parent=self, delay=3)
        self.add_component(self.sender)
        self.add_component(self.server_receiver)
        self.add_component(self.server_sender)
        self.add_component(self.receiver)
        self.add_component(self.subnet_a1)
        self.add_component(self.subnet_a2)
        self.add_component(self.subnet_b1)
        self.add_component(self.subnet_b2)
        self.add_coupling(self.sender.output["packet_out"], self.subnet_a1.input["packet_in"])
        self.add_coupling(self.subnet_a1.output["packet_out"], self.server_receiver.input["packet_in"])
        self.add_coupling(self.server_receiver.output["ack_out"], self.subnet_a2.input["packet_in"])
        self.add_coupling(self.subnet_a2.output["packet_out"], self.sender.input["ack_in"])
        self.add_coupling(self.server_receiver.output["packet_out"], self.server_sender.input["packet_in"])
        self.add_coupling(self.server_sender.output["packet_out"], self.subnet_b1.input["packet_in"])
        self.add_coupling(self.subnet_b1.output["packet_out"], self.receiver.input["packet_in"])
        self.add_coupling(self.receiver.output["ack_out"], self.subnet_b2.input["packet_in"])
        self.add_coupling(self.subnet_b2.output["packet_out"], self.server_sender.input["ack_in"])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=10000)
    args = parser.parse_args()

    root = System(name="system", parent=None)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.simulation_time)

    for line in sys.stdin:
        try:
            time_str, type_str, value_str = line.strip().split(maxsplit=2)
            time_ms = float(time_str.replace(":", "."))
            type = type_str
            value = int(value_str)
            if type == "control":
                root.sender.input["control_in"].add({"added": value, "total_remaining": root.sender.packets_to_send + value})
            elif type == "request":
                root.server_sender.input["request_in"].add({"allowed": value == 1})
        except Exception as e:
            pass

if __name__ == "__main__":
    main()