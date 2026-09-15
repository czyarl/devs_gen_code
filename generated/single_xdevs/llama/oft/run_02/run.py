import argparse
import json
import logging
import random
import sys
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Configure logging
logging.basicConfig(stream=sys.stderr, level=logging.INFO)

class Sender(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("control", "control"))
        self.add_out_port(Port("packet", "packet"))
        self.add_out_port(Port("ack", "ack"))
        self.total_packets_to_send = 0
        self.packets_remaining = 0
        self.seq = 1
        self.bit = 0
        self.preparing = False
        self.waiting_for_ack = False

    def initialize(self):
        self.hold_in("idle", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        if self.phase == "preparing":
            self.output["packet"].add({"seq": self.seq, "bit": self.bit, "is_retry": False})
            self.waiting_for_ack = True
            self.hold_in("waiting_for_ack", 20)
        elif self.phase == "timeout":
            self.output["packet"].add({"seq": self.seq, "bit": self.bit, "is_retry": True})
            self.hold_in("waiting_for_ack", 20)
        elif self.phase == "idle" and self.packets_remaining > 0:
            self.preparing = True
            self.hold_in("preparing", 10)

    def deltext(self, e):
        if self.input["control"].value:
            self.total_packets_to_send += self.input["control"].value
            self.packets_remaining += self.input["control"].value
            if self.phase == "idle":
                self.hold_in("preparing", 10)
        self.hold_in(self.phase, 0)

    def exit(self):
        print(json.dumps({"timestamp_ms": 0, "model": "sender", "type": "final_state", "val": {}}), file=sys.stdout, flush=True)

class ServerReceiver(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("packet", "packet"))
        self.add_out_port(Port("ack", "ack"))
        self.expected_bit = 0
        self.storage_queue = deque()

    def initialize(self):
        self.hold_in("idle", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        if self.phase == "processing":
            self.storage_queue.append({"seq": self.seq, "bit": self.bit})
            self.output["ack"].add({"bit": self.expected_bit})
            self.expected_bit = 1 - self.expected_bit
            self.hold_in("idle", 0)

    def deltext(self, e):
        if self.input["packet"].value:
            self.seq = self.input["packet"].value["seq"]
            self.bit = self.input["packet"].value["bit"]
            self.hold_in("processing", 3)

    def exit(self):
        print(json.dumps({"timestamp_ms": 0, "model": "server_receiver", "type": "final_state", "val": {}}), file=sys.stdout, flush=True)

class ServerSender(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("packet", "packet"))
        self.add_out_port(Port("packet", "packet"))
        self.add_out_port(Port("ack", "ack"))
        self.storage_queue = deque()
        self.download_allowed = False
        self.waiting_for_ack = False
        self.bit = 0

    def initialize(self):
        self.hold_in("idle", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        if self.phase == "sending":
            packet = self.storage_queue.popleft()
            self.output["packet"].add(packet)
            self.waiting_for_ack = True
            self.bit = 1 - self.bit
            self.hold_in("waiting_for_ack", 20)
        elif self.phase == "timeout":
            self.output["packet"].add({"seq": 1, "bit": self.bit})
            self.hold_in("waiting_for_ack", 20)

    def deltext(self, e):
        if self.input["download_valve"].value is not None:
            self.download_allowed = self.input["download_valve"].value
        if self.input["packet"].value:
            self.storage_queue.append(self.input["packet"].value)
        if self.download_allowed and self.storage_queue and not self.waiting_for_ack:
            self.hold_in("sending", 0)

    def exit(self):
        print(json.dumps({"timestamp_ms": 0, "model": "server_sender", "type": "final_state", "val": {}}), file=sys.stdout, flush=True)

class Receiver(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("packet", "packet"))
        self.add_out_port(Port("ack", "ack"))

    def initialize(self):
        self.hold_in("idle", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        if self.phase == "processing":
            self.hold_in("idle", 0)
            self.output["ack"].add({"bit": self.bit})

    def deltext(self, e):
        if self.input["packet"].value:
            self.bit = self.input["packet"].value["bit"]
            self.hold_in("processing", 10)

    def exit(self):
        print(json.dumps({"timestamp_ms": 0, "model": "receiver", "type": "final_state", "val": {}}), file=sys.stdout, flush=True)

class Subnet(Atomic):
    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("packet", "packet"))
        self.add_out_port(Port("packet", "packet"))
        self.delay = delay

    def initialize(self):
        self.hold_in("idle", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        if self.phase == "transmitting":
            self.output["packet"].add(self.packet)
            self.hold_in("idle", 0)

    def deltext(self, e):
        if self.input["packet"].value:
            self.packet = self.input["packet"].value
            self.hold_in("transmitting", self.delay)

    def exit(self):
        print(json.dumps({"timestamp_ms": 0, "model": "subnet", "type": "final_state", "val": {}}), file=sys.stdout, flush=True)

class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None, simulation_time: float):
        super().__init__(name)
        self.parent = parent

        self.sender = Sender(name="sender", parent=self)
        self.add_component(self.sender)

        self.server_receiver = ServerReceiver(name="server_receiver", parent=self)
        self.add_component(self.server_receiver)

        self.server_sender = ServerSender(name="server_sender", parent=self)
        self.add_component(self.server_sender)

        self.receiver = Receiver(name="receiver", parent=self)
        self.add_component(self.receiver)

        self.subnet_a1 = Subnet(name="subnet_a1", parent=self, delay=3)
        self.add_component(self.subnet_a1)

        self.subnet_a2 = Subnet(name="subnet_a2", parent=self, delay=3)
        self.add_component(self.subnet_a2)

        self.subnet_b1 = Subnet(name="subnet_b1", parent=self, delay=3)
        self.add_component(self.subnet_b1)

        self.subnet_b2 = Subnet(name="subnet_b2", parent=self, delay=3)
        self.add_component(self.subnet_b2)

        self.add_coupling(self.sender.output["packet"], self.subnet_a1.input["packet"])
        self.add_coupling(self.subnet_a1.output["packet"], self.server_receiver.input["packet"])
        self.add_coupling(self.server_receiver.output["ack"], self.subnet_a2.input["packet"])
        self.add_coupling(self.subnet_a2.output["ack"], self.sender.input["ack"])

        self.add_coupling(self.server_receiver.output["packet"], self.server_sender.input["packet"])
        self.add_coupling(self.server_sender.output["packet"], self.subnet_b1.input["packet"])
        self.add_coupling(self.subnet_b1.output["packet"], self.receiver.input["packet"])
        self.add_coupling(self.receiver.output["ack"], self.subnet_b2.input["packet"])
        self.add_coupling(self.subnet_b2.output["ack"], self.server_sender.input["ack"])

        self.add_in_port(Port("control", "control"))
        self.add_coupling(self.input["control"], self.sender.input["control"])

        self.add_in_port(Port("request", "download_valve"))
        self.add_coupling(self.input["request"], self.server_sender.input["download_valve"])

    def exit(self):
        pass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=10000)
    args = parser.parse_args()

    root = System(name="system", parent=None, simulation_time=args.simulation_time)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()

    for line in sys.stdin:
        try:
            time_str, cmd_type, value = line.strip().split(maxsplit=2)
            hours, minutes, seconds, milliseconds = map(int, time_str.split(":"))
            time_ms = (hours * 3600 + minutes * 60 + seconds) * 1000 + milliseconds
            if cmd_type == "control":
                root.sender.total_packets_to_send += int(value)
                root.sender.packets_remaining += int(value)
                if root.sender.phase == "idle":
                    coord.schedule_event(time_ms, {"type": "control_cmd", "val": {"added": int(value), "total_remaining": root.sender.total_packets_to_send}})
                    root.sender.hold_in("preparing", 10)
            elif cmd_type == "request":
                coord.schedule_event(time_ms, {"type": "download_valve_change", "val": {"allowed": bool(int(value))}})
                root.server_sender.download_allowed = bool(int(value))
        except Exception as e:
            logging.error(f"Error processing input line: {e}")

    coord.simulate_time(args.simulation_time)

if __name__ == "__main__":
    main()