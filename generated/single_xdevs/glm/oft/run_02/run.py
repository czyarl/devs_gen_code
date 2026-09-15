import argparse
import sys
import json
import logging
from collections import deque

# xdevs imports
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Configure logging to stderr
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Helper Functions & Constants
# -----------------------------------------------------------------------------

def log_event(timestamp_ms, model_name, event_type, val):
    """Helper to print JSONL to stdout."""
    event = {
        "timestamp_ms": timestamp_ms,
        "model": model_name,
        "type": event_type,
        "val": val
    }
    print(json.dumps(event), file=sys.stdout, flush=True)

# -----------------------------------------------------------------------------
# Atomic Models
# -----------------------------------------------------------------------------

class Sender(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.i_control = Port(int, "i_control")
        self.i_ack = Port(dict, "i_ack")
        self.o_data = Port(dict, "o_data")
        
        self.add_in_port(self.i_control)
        self.add_in_port(self.i_ack)
        self.add_out_port(self.o_data)

        # State
        self.total_packets_to_send = 0
        self.seq = 1
        self.bit = 0
        self.current_packet = None
        self.waiting_for_ack = False
        self.preparation_time = 10.0 
        self.timeout = 20.0 
        
        self.phase = "idle"
        self.sigma = float('inf')

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.phase == "sending":
            if self.current_packet:
                self.o_data.add(self.current_packet)

    def deltint(self):
        if self.phase == "preparing":
            self.current_packet = {"seq": self.seq, "bit": self.bit}
            self.waiting_for_ack = True
            self.hold_in("sending", 0)
            
            log_event(self.time * 1000, self.name, "packet_sent", 
                      {"seq": self.seq, "bit": self.bit, "is_retry": False})
            
        elif self.phase == "sending":
            self.hold_in("waiting", self.timeout)
            
        elif self.phase == "timeout":
            self.hold_in("sending", 0)
            log_event(self.time * 1000, self.name, "timeout", {"seq": self.seq})
            log_event(self.time * 1000, self.name, "packet_sent", 
                      {"seq": self.seq, "bit": self.bit, "is_retry": True})
            
        elif self.phase == "idle":
            self.hold_in("idle", float('inf'))

    def deltext(self, e):
        if self.i_control.values:
            added = sum(self.i_control.values)
            self.total_packets_to_send += added
            
            log_event(self.time * 1000, self.name, "control_cmd", 
                      {"added": added, "total_remaining": self.total_packets_to_send})
            
            if self.phase == "idle" and self.total_packets_to_send > 0:
                self.hold_in("preparing", self.preparation_time)
                log_event(self.time * 1000, self.name, "preparation_started", {"duration": 10000})

        if self.i_ack.values:
            for ack in self.i_ack.values:
                received_bit = ack['bit']
                log_event(self.time * 1000, self.name, "ack_received", {"bit": received_bit})
                
                if self.waiting_for_ack and received_bit == self.bit:
                    self.waiting_for_ack = False
                    self.bit = 1 - self.bit
                    self.seq += 1
                    self.total_packets_to_send -= 1
                    
                    if self.total_packets_to_send > 0:
                        self.hold_in("preparing", self.preparation_time)
                        log_event(self.time * 1000, self.name, "preparation_started", {"duration": 10000})
                    else:
                        self.hold_in("idle", float('inf'))
        
        if self.phase == "waiting":
            self.hold_in("waiting", self.sigma - e)

    def exit(self):
        pass


class ServerReceiver(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        self.i_data = Port(dict, "i_data")
        self.o_ack = Port(dict, "o_ack")
        self.o_storage = Port(dict, "o_storage")
        
        self.add_in_port(self.i_data)
        self.add_out_port(self.o_ack)
        self.add_out_port(self.o_storage)

        self.expected_bit = 0
        self.processing_time = 3.0
        self.current_packet = None

    def initialize(self):
        self.hold_in("passive", float('inf'))

    def lambdaf(self):
        if self.phase == "sending_ack":
            if self.current_packet:
                self.o_ack.add({"bit": self.current_packet['bit']})
                log_event(self.time * 1000, self.name, "ack_sent_to_sender", {"bit": self.current_packet['bit']})
                
                if self.current_packet['bit'] == self.expected_bit:
                    self.o_storage.add(self.current_packet)
                    self.expected_bit = 1 - self.expected_bit

    def deltint(self):
        if self.phase == "processing":
            self.hold_in("sending_ack", 0)
        elif self.phase == "sending_ack":
            self.current_packet = None
            self.hold_in("passive", float('inf'))
        elif self.phase == "passive":
            self.hold_in("passive", float('inf'))

    def deltext(self, e):
        if self.i_data.values:
            for pkt in self.i_data.values:
                log_event(self.time * 1000, self.name, "packet_received", {"seq": pkt['seq'], "bit": pkt['bit']})
                self.current_packet = pkt
                self.hold_in("processing", self.processing_time)

    def exit(self):
        pass


class ServerSender(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        self.i_storage = Port(dict, "i_storage")
        self.i_request = Port(int, "i_request")
        self.i_ack = Port(dict, "i_ack")
        self.o_data = Port(dict, "o_data")
        
        self.add_in_port(self.i_storage)
        self.add_in_port(self.i_request)
        self.add_in_port(self.i_ack)
        self.add_out_port(self.o_data)

        self.storage_queue = deque()
        self.download_allowed = False
        self.waiting_for_ack = False
        self.current_packet = None
        self.bit = 0 

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.phase == "sending":
            if self.current_packet:
                self.o_data.add(self.current_packet)
                log_event(self.time * 1000, self.name, "packet_forwarded", 
                          {"seq": self.current_packet['seq'], "bit": self.bit})

    def deltint(self):
        if self.phase == "sending":
            self.waiting_for_ack = True
            self.hold_in("waiting", 20.0)
        elif self.phase == "timeout":
            self.hold_in("sending", 0)
        elif self.phase == "idle":
            self.hold_in("idle", float('inf'))

    def deltext(self, e):
        if self.i_request.values:
            val = list(self.i_request.values)[-1]
            new_allowed = (val == 1)
            if self.download_allowed != new_allowed:
                self.download_allowed = new_allowed
                log_event(self.time * 1000, self.name, "download_valve_change", {"allowed": self.download_allowed})

        if self.i_storage.values:
            for pkt in self.i_storage.values:
                self.storage_queue.append(pkt)

        if self.i_ack.values:
            for ack in self.i_ack.values:
                log_event(self.time * 1000, self.name, "ack_received_from_receiver", {"bit": ack['bit']})
                if self.waiting_for_ack and ack['bit'] == self.bit:
                    self.waiting_for_ack = False
                    self.bit = 1 - self.bit
                    self.current_packet = None

        if self.phase == "idle":
            if self.storage_queue and self.download_allowed:
                self.current_packet = self.storage_queue.popleft()
                self.hold_in("sending", 0)
            else:
                self.hold_in("idle", float('inf'))
                
        elif self.phase == "waiting":
            if not self.waiting_for_ack:
                if self.storage_queue and self.download_allowed:
                    self.current_packet = self.storage_queue.popleft()
                    self.hold_in("sending", 0)
                else:
                    self.hold_in("idle", float('inf'))
            else:
                self.hold_in("waiting", self.sigma - e)
                
        elif self.phase == "timeout":
             pass

    def exit(self):
        pass


class Receiver(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        self.i_data = Port(dict, "i_data")
        self.o_ack = Port(dict, "o_ack")
        
        self.add_in_port(self.i_data)
        self.add_out_port(self.o_ack)
        
        self.processing_time = 10.0
        self.current_packet = None

    def initialize(self):
        self.hold_in("passive", float('inf'))

    def lambdaf(self):
        if self.phase == "sending_ack":
            if self.current_packet:
                self.o_ack.add({"bit": self.current_packet['bit']})
                log_event(self.time * 1000, self.name, "ack_sent", {"bit": self.current_packet['bit']})

    def deltint(self):
        if self.phase == "processing":
            self.hold_in("sending_ack", 0)
        elif self.phase == "sending_ack":
            self.current_packet = None
            self.hold_in("passive", float('inf'))
        elif self.phase == "passive":
            self.hold_in("passive", float('inf'))

    def deltext(self, e):
        if self.i_data.values:
            for pkt in self.i_data.values:
                self.current_packet = pkt
                self.hold_in("processing", self.processing_time)
                log_event(self.time * 1000, self.name, "processing_started", 
                          {"seq": pkt['seq'], "duration": 10000})

    def exit(self):
        pass


class Subnet(Atomic):
    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        
        self.i_in = Port(object, "i_in")
        self.o_out = Port(object, "o_out")
        
        self.add_in_port(self.i_in)
        self.add_out_port(self.o_out)
        
        self.queue = deque()

    def initialize(self):
        self.hold_in("passive", float('inf'))

    def lambdaf(self):
        if self.phase == "delivering" and self.queue:
            self.o_out.add(self.queue[0])

    def deltint(self):
        if self.phase == "delivering":
            self.queue.popleft()
            if self.queue:
                self.hold_in("delivering", self.delay)
            else:
                self.hold_in("passive", float('inf'))
        elif self.phase == "passive":
            self.hold_in("passive", float('inf'))

    def deltext(self, e):
        if self.i_in.values:
            for val in self.i_in.values:
                self.queue.append(val)
            
            if self.phase == "passive":
                self.hold_in("delivering", self.delay)
            else:
                pass

    def exit(self):
        pass


class InputInjector(Atomic):
    def __init__(self, name: str, parent: Coupled | None, commands: list):
        super().__init__(name)
        self.parent = parent
        self.commands = commands
        self.commands.sort(key=lambda x: x[0])
        
        self.o_control = Port(int, "o_control")
        self.o_request = Port(int, "o_request")
        
        self.add_out_port(self.o_control)
        self.add_out_port(self.o_request)
        
        self.idx = 0

    def initialize(self):
        if self.commands:
            next_time = self.commands[0][0]
            self.hold_in("active", next_time)
        else:
            self.hold_in("done", float('inf'))

    def lambdaf(self):
        if self.phase == "active" and self.idx < len(self.commands):
            _, cmd_type, val = self.commands[self.idx]
            if cmd_type == "control":
                self.o_control.add(val)
            elif cmd_type == "request":
                self.o_request.add(val)

    def deltint(self):
        if self.phase == "active":
            self.idx += 1
            if self.idx < len(self.commands):
                next_time = self.commands[self.idx][0] - self.commands[self.idx-1][0]
                self.hold_in("active", next_time)
            else:
                self.hold_in("done", float('inf'))
        elif self.phase == "done":
            self.hold_in("done", float('inf'))

    def deltext(self, e):
        pass

    def exit(self):
        pass


# -----------------------------------------------------------------------------
# Coupled Models
# -----------------------------------------------------------------------------

class DropboxSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None, commands: list):
        super().__init__(name)
        self.parent = parent
        
        self.injector = InputInjector("injector", self, commands)
        self.sender = Sender("sender", self)
        self.server_receiver = ServerReceiver("server_receiver", self)
        self.server_sender = ServerSender("server_sender", self)
        self.receiver = Receiver("receiver", self)
        
        self.subnet_a1 = Subnet("subnet_a1", self, 3.0)
        self.subnet_a2 = Subnet("subnet_a2", self, 3.0)
        self.subnet_b1 = Subnet("subnet_b1", self, 3.0)
        self.subnet_b2 = Subnet("subnet_b2", self, 3.0)
        
        self.add_component(self.injector)
        self.add_component(self.sender)
        self.add_component(self.server_receiver)
        self.add_component(self.server_sender)
        self.add_component(self.receiver)
        self.add_component(self.subnet_a1)
        self.add_component(self.subnet_a2)
        self.add_component(self.subnet_b1)
        self.add_component(self.subnet_b2)
        
        self.add_coupling(self.injector.o_control, self.sender.i_control)
        self.add_coupling(self.injector.o_request, self.server_sender.i_request)
        
        self.add_coupling(self.sender.o_data, self.subnet_a1.i_in)
        self.add_coupling(self.subnet_a1.o_out, self.server_receiver.i_data)
        
        self.add_coupling(self.server_receiver.o_ack, self.subnet_a2.i_in)
        self.add_coupling(self.subnet_a2.o_out, self.sender.i_ack)
        
        self.add_coupling(self.server_receiver.o_storage, self.server_sender.i_storage)
        
        self.add_coupling(self.server_sender.o_data, self.subnet_b1.i_in)
        self.add_coupling(self.subnet_b1.o_out, self.receiver.i_data)
        
        self.add_coupling(self.receiver.o_ack, self.subnet_b2.i_in)
        self.add_coupling(self.subnet_b2.o_out, self.server_sender.i_ack)

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def parse_stdin():
    commands = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        
        time_str = parts[0]
        cmd_type = parts[1]
        val_str = parts[2]
        
        time_parts = time_str.split(':')
        seconds = 0
        if len(time_parts) == 3:
            h, m, s = time_parts
            seconds = int(h) * 3600 + int(m) * 60 + float(s)
        elif len(time_parts) == 4:
            h, m, s, ms = time_parts
            seconds = int(h) * 3600 + int(m) * 60 + int(s) + float(ms) / 1000.0
            
        val = int(val_str)
        commands.append((seconds, cmd_type, val))
        
    return commands

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=10000000.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    commands = parse_stdin()
    
    root = DropboxSystem(name="dropbox_system", parent=None, commands=commands)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.simulation_time)

if __name__ == "__main__":
    main()