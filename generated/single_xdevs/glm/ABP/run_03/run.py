import argparse
import sys
import json
import logging

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Configure logging to stderr
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Helper to print JSONL to stdout
def print_event(time, entity, event, payload):
    print(json.dumps({
        "time": round(float(time), 2),
        "entity": entity,
        "event": event,
        "payload": payload
    }), file=sys.stdout, flush=True)

class Sender(Atomic):
    def __init__(self, name: str, parent: Coupled | None, total_packets: int, timeout: float, preparation_delay: float):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.add_in_port(Port(dict, "i_ack"))
        self.add_out_port(Port(dict, "o_data"))
        
        # Configuration
        self.total_packets = total_packets
        self.timeout = timeout
        self.preparation_delay = preparation_delay
        
        # State
        self.seq_num = 1
        self.bit = 0
        self.packets_sent_count = 0
        self.current_packet = None
        self.is_retry = False
        
        # Phases: "idle", "preparing", "waiting_ack", "done"
        self.hold_in("idle", float('inf'))

    def initialize(self):
        self.hold_in("idle", 0.0)

    def lambdaf(self):
        if self.phase == "preparing":
            packet = {
                "seq_num": self.seq_num,
                "bit": self.bit
            }
            self.output["o_data"].add(packet)
            
            print_event(
                time=self.time,
                entity="sender",
                event="packet_sent",
                payload={
                    "seq_num": self.seq_num,
                    "bit": self.bit,
                    "is_retry": self.is_retry
                }
            )

    def deltint(self):
        if self.phase == "idle":
            if self.packets_sent_count < self.total_packets:
                print_event(
                    time=self.time,
                    entity="sender",
                    event="delay_start",
                    payload={"type": "preparation", "duration": self.preparation_delay}
                )
                self.hold_in("preparing", self.preparation_delay)
            else:
                self.hold_in("done", float('inf'))
        
        elif self.phase == "preparing":
            self.current_packet = {"seq_num": self.seq_num, "bit": self.bit}
            self.hold_in("waiting_ack", self.timeout)
            
        elif self.phase == "waiting_ack":
            # Timeout occurred, retransmit
            self.is_retry = True
            print_event(
                time=self.time,
                entity="sender",
                event="delay_start",
                payload={"type": "preparation", "duration": self.preparation_delay}
            )
            self.hold_in("preparing", self.preparation_delay)

    def deltext(self, e: float):
        if self.phase == "waiting_ack" and not self.input["i_ack"].empty:
            ack = self.input["i_ack"].get_val()
            ack_bit = ack.get("bit")
            
            is_valid = (ack_bit == self.current_packet["bit"])
            
            print_event(
                time=self.time,
                entity="sender",
                event="ack_received",
                payload={"ack_bit": ack_bit, "is_valid": is_valid}
            )
            
            if is_valid:
                self.packets_sent_count += 1
                self.seq_num += 1
                self.bit = 1 - self.bit
                self.is_retry = False
                
                if self.packets_sent_count < self.total_packets:
                    print_event(
                        time=self.time,
                        entity="sender",
                        event="delay_start",
                        payload={"type": "preparation", "duration": self.preparation_delay}
                    )
                    self.hold_in("preparing", self.preparation_delay)
                else:
                    self.hold_in("done", float('inf'))
                return

        # If we reach here, either invalid ACK or unexpected state
        # Continue waiting or preserve state
        if self.phase == "waiting_ack":
            self.hold_in("waiting_ack", self.sigma - e)
        else:
            self.hold_in(self.phase, self.sigma - e)

    def exit(self):
        pass

class Receiver(Atomic):
    def __init__(self, name: str, parent: Coupled | None, processing_delay: float):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.add_in_port(Port(dict, "i_data"))
        self.add_out_port(Port(dict, "o_ack"))
        
        # Configuration
        self.processing_delay = processing_delay
        
        # State
        self.buffer = None
        self.busy = False
        
        # Phases: "idle", "processing"
        self.hold_in("idle", float('inf'))

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.phase == "processing":
            if self.buffer:
                ack = {"bit": self.buffer["bit"]}
                self.output["o_ack"].add(ack)

    def deltint(self):
        if self.phase == "processing":
            if self.buffer:
                print_event(
                    time=self.time,
                    entity="receiver",
                    event="packet_received",
                    payload={"seq_num": self.buffer["seq_num"], "bit": self.buffer["bit"]}
                )
                self.buffer = None
                self.busy = False
                self.hold_in("idle", float('inf'))

    def deltext(self, e: float):
        if not self.input["i_data"].empty:
            packet = self.input["i_data"].get_val()
            
            if not self.busy:
                self.buffer = packet
                self.busy = True
                print_event(
                    time=self.time,
                    entity="receiver",
                    event="delay_start",
                    payload={"type": "processing", "duration": self.processing_delay}
                )
                self.hold_in("processing", self.processing_delay)
                return
        
        # If we didn't accept the packet (busy) or no packet
        # Preserve state
        if self.phase == "processing":
            self.hold_in("processing", self.sigma - e)
        else:
            self.hold_in(self.phase, self.sigma - e)

    def exit(self):
        pass

class Subnet(Atomic):
    def __init__(self, name: str, parent: Coupled | None, channel_delay: float, seed: int, direction: str):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.add_in_port(Port(dict, "i_in"))
        self.add_out_port(Port(dict, "o_out"))
        
        # Configuration
        self.channel_delay = channel_delay
        self.direction = direction
        
        # State
        self.noise_x = seed
        self.packet_in_transit = None
        
        # Phases: "idle", "transmitting"
        self.hold_in("idle", float('inf'))

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.phase == "transmitting" and self.packet_in_transit:
            self.output["o_out"].add(self.packet_in_transit)

    def deltint(self):
        if self.phase == "transmitting":
            self.packet_in_transit = None
            self.hold_in("idle", float('inf'))

    def deltext(self, e: float):
        if not self.input["i_in"].empty:
            packet = self.input["i_in"].get_val()
            
            x_new = (17 * self.noise_x + 11) % 100
            behavior = "drop" if x_new < 10 else "pass"
            
            print_event(
                time=self.time,
                entity="subnet",
                event="packet_get",
                payload={
                    "behavior": behavior,
                    "channel": self.direction,
                    "noise_value": x_new
                }
            )
            
            self.noise_x = x_new
            
            if behavior == "pass":
                self.packet_in_transit = packet
                self.hold_in("transmitting", self.channel_delay)
            else:
                self.hold_in("idle", float('inf'))
            return

        # If no input (should not happen if deltext called)
        if self.phase == "transmitting":
            self.hold_in("transmitting", self.sigma - e)
        else:
            self.hold_in(self.phase, self.sigma - e)

    def exit(self):
        pass

class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None, args):
        super().__init__(name)
        self.parent = parent
        
        self.sender = Sender(name="sender", parent=self, 
                             total_packets=args.total_packets, 
                             timeout=args.timeout, 
                             preparation_delay=args.sender_delay)
        
        self.receiver = Receiver(name="receiver", parent=self, 
                                  processing_delay=args.receiver_delay)
        
        self.subnet1 = Subnet(name="subnet1", parent=self, 
                              channel_delay=args.channel_delay, 
                              seed=args.seed, 
                              direction="forward")
        
        self.subnet2 = Subnet(name="subnet2", parent=self, 
                              channel_delay=args.channel_delay, 
                              seed=args.seed, 
                              direction="backward")
        
        self.add_component(self.sender)
        self.add_component(self.receiver)
        self.add_component(self.subnet1)
        self.add_component(self.subnet2)
        
        # Couplings
        self.add_coupling(self.sender.output["o_data"], self.subnet1.input["i_in"])
        self.add_coupling(self.subnet1.output["o_out"], self.receiver.input["i_data"])
        self.add_coupling(self.receiver.output["o_ack"], self.subnet2.input["i_in"])
        self.add_coupling(self.subnet2.output["o_out"], self.sender.input["i_ack"])

def main():
    parser = argparse.ArgumentParser(description="Reliable Data Transfer Simulation with DEVS")
    parser.add_argument("--total_packets", type=int, required=True, help="Total packets to send")
    parser.add_argument("--seed", type=int, default=42, help="Noise generator seed")
    parser.add_argument("--timeout", type=int, default=20, help="Sender timeout duration (ms)")
    parser.add_argument("--sender_delay", type=int, default=10, help="Sender preparation delay (ms)")
    parser.add_argument("--receiver_delay", type=int, default=10, help="Receiver processing delay (ms)")
    parser.add_argument("--channel_delay", type=int, default=3, help="Subnet transmission delay (ms)")
    parser.add_argument("--simulate_time", type=int, default=1000, help="Total simulation time (ms)")
    
    args = parser.parse_args()
    
    root = System(name="system", parent=None, args=args)
    coord = Coordinator(root, clock=SimulationClock(0))
    
    coord.initialize()
    coord.simulate_time(args.simulate_time)

if __name__ == "__main__":
    main()