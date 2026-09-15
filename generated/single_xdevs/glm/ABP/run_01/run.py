import sys
import argparse
import json
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# --- Helper for JSONL Output ---
def log_event(time: float, entity: str, event: str, payload: dict):
    """Prints a JSONL record to stdout."""
    record = {
        "time": round(time, 2),
        "entity": entity,
        "event": event,
        "payload": payload
    }
    print(json.dumps(record), file=sys.stdout, flush=True)

# --- Atomic Models ---

class Sender(Atomic):
    def __init__(self, name: str, parent: Coupled | None, 
                 total_packets: int, timeout: float, sender_delay: float):
        super().__init__(name)
        self.parent = parent
        
        # Configuration
        self.total_packets = total_packets
        self.timeout = timeout
        self.sender_delay = sender_delay
        
        # Ports
        self.ack_in = self.add_in_port(Port(dict, "ack_in"))
        self.packet_out = self.add_out_port(Port(dict, "packet_out"))
        
        # State
        self.seq_num = 1
        self.bit = 0
        self.packets_sent_count = 0
        self.is_retrying = False
        
        # Phases: "idle", "preparing", "waiting", "done"
        self.phase = "idle"
        self.sigma = float('inf')

    def initialize(self):
        self.phase = "idle"
        self.sigma = 0.0
        self.hold_in("idle", 0.0)

    def deltint(self):
        if self.phase == "idle":
            if self.packets_sent_count < self.total_packets:
                self.is_retrying = False
                self.phase = "preparing"
                self.sigma = self.sender_delay
                log_event(self.clock.get_time(), "sender", "delay_start", {
                    "type": "preparation", "duration": self.sender_delay
                })
            else:
                self.phase = "done"
                self.sigma = float('inf')
            self.hold_in(self.phase, self.sigma)
            
        elif self.phase == "preparing":
            self.phase = "waiting"
            self.sigma = self.timeout
            self.hold_in("waiting", self.sigma)
            
        elif self.phase == "waiting":
            # Timeout occurred
            self.is_retrying = True
            self.phase = "preparing"
            self.sigma = self.sender_delay
            log_event(self.clock.get_time(), "sender", "delay_start", {
                "type": "preparation", "duration": self.sender_delay
            })
            self.hold_in("preparing", self.sigma)
            
        elif self.phase == "done":
            self.hold_in("done", float('inf'))

    def deltext(self, e: float):
        if self.phase == "waiting" and self.ack_in:
            for ack in self.ack_in.values:
                ack_bit = ack.get("bit")
                is_valid = (ack_bit == self.bit)
                
                log_event(self.clock.get_time(), "sender", "ack_received", {
                    "ack_bit": ack_bit, "is_valid": is_valid
                })
                
                if is_valid:
                    self.packets_sent_count += 1
                    if self.packets_sent_count < self.total_packets:
                        self.seq_num += 1
                        self.bit = 1 - self.bit
                        self.is_retrying = False
                        self.phase = "preparing"
                        self.sigma = self.sender_delay
                        log_event(self.clock.get_time(), "sender", "delay_start", {
                            "type": "preparation", "duration": self.sender_delay
                        })
                    else:
                        self.phase = "done"
                        self.sigma = float('inf')
                    self.hold_in(self.phase, self.sigma)
                    return
        
        # If we didn't handle a valid ACK, we stay in waiting (or whatever phase we were in)
        # Adjust sigma for elapsed time
        if self.phase != "done":
            self.sigma = self.sigma - e
            self.hold_in(self.phase, self.sigma)

    def lambdaf(self):
        if self.phase == "preparing":
            # Output packet
            payload = {
                "seq_num": self.seq_num,
                "bit": self.bit,
                "is_retry": self.is_retrying
            }
            self.packet_out.add(payload)
            log_event(self.clock.get_time(), "sender", "packet_sent", payload)

    def exit(self):
        pass


class Receiver(Atomic):
    def __init__(self, name: str, parent: Coupled | None, receiver_delay: float):
        super().__init__(name)
        self.parent = parent
        
        self.receiver_delay = receiver_delay
        
        self.packet_in = self.add_in_port(Port(dict, "packet_in"))
        self.ack_out = self.add_out_port(Port(dict, "ack_out"))
        
        self.phase = "idle"
        self.sigma = float('inf')
        self.buffered_packet = None
        self.buffer_is_full = False

    def initialize(self):
        self.phase = "idle"
        self.sigma = float('inf')
        self.buffered_packet = None
        self.buffer_is_full = False
        self.hold_in("idle", float('inf'))

    def deltint(self):
        if self.phase == "processing":
            # Processing done, send ACK
            if self.buffered_packet:
                bit = self.buffered_packet.get("bit")
                seq = self.buffered_packet.get("seq_num")
                
                # Log packet received successfully
                log_event(self.clock.get_time(), "receiver", "packet_received", {
                    "seq_num": seq, "bit": bit
                })
                
                self.phase = "sending_ack"
                self.sigma = 0.0
                self.hold_in("sending_ack", 0.0)
            else:
                self.phase = "idle"
                self.hold_in("idle", float('inf'))
                
        elif self.phase == "sending_ack":
            # ACK sent (in lambdaf), clear buffer
            self.buffered_packet = None
            self.buffer_is_full = False
            self.phase = "idle"
            self.sigma = float('inf')
            self.hold_in("idle", float('inf'))

    def deltext(self, e: float):
        # Check for incoming packet
        if self.packet_in:
            for packet in self.packet_in.values:
                if not self.buffer_is_full:
                    # Buffer the packet
                    self.buffered_packet = packet
                    self.buffer_is_full = True
                    
                    # Start processing delay
                    self.phase = "processing"
                    self.sigma = self.receiver_delay
                    log_event(self.clock.get_time(), "receiver", "delay_start", {
                        "type": "processing", "duration": self.receiver_delay
                    })
                    self.hold_in("processing", self.receiver_delay)
                    return # Only process one packet at a time
        
        # If we didn't accept a packet, maintain state (adjust sigma if active)
        if self.phase != "idle":
            self.sigma = self.sigma - e
            self.hold_in(self.phase, self.sigma)

    def lambdaf(self):
        if self.phase == "sending_ack" and self.buffered_packet:
            bit = self.buffered_packet.get("bit")
            self.ack_out.add({"bit": bit})

    def exit(self):
        pass


class Subnet(Atomic):
    def __init__(self, name: str, parent: Coupled | None, 
                 channel_delay: float, seed: int, channel_id: str):
        super().__init__(name)
        self.parent = parent
        
        self.channel_delay = channel_delay
        self.noise = seed
        self.channel_id = channel_id # "forward" or "backward"
        
        self.packet_in = self.add_in_port(Port(dict, "packet_in"))
        self.packet_out = self.add_out_port(Port(dict, "packet_out"))
        
        self.phase = "idle"
        self.sigma = float('inf')
        self.stored_packet = None

    def initialize(self):
        self.phase = "idle"
        self.sigma = float('inf')
        self.stored_packet = None
        self.hold_in("idle", float('inf'))

    def deltint(self):
        if self.phase == "transmitting":
            # Transmission delay over, send packet out
            self.phase = "idle"
            self.sigma = float('inf')
            self.hold_in("idle", float('inf'))

    def deltext(self, e: float):
        if self.packet_in:
            for packet in self.packet_in.values:
                # Calculate noise and fate
                # x_new = (17 * x_old + 11) mod 100
                x_new = (17 * self.noise + 11) % 100
                
                behavior = "drop"
                if x_new >= 10:
                    behavior = "pass"
                
                # Log fate
                log_event(self.clock.get_time(), "subnet", "packet_get", {
                    "behavior": behavior,
                    "channel": self.channel_id,
                    "noise_value": x_new
                })
                
                # Update noise state
                self.noise = x_new
                
                if behavior == "pass":
                    # Store packet and schedule transmission
                    self.stored_packet = packet
                    self.phase = "transmitting"
                    self.sigma = self.channel_delay
                    self.hold_in("transmitting", self.channel_delay)
                else:
                    # Packet dropped, stay idle
                    self.phase = "idle"
                    self.sigma = float('inf')
                    self.hold_in("idle", float('inf'))
                return

    def lambdaf(self):
        if self.phase == "transmitting" and self.stored_packet:
            self.packet_out.add(self.stored_packet)

    def exit(self):
        pass


# --- Coupled Model ---

class ReliableSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None, args):
        super().__init__(name)
        self.parent = parent
        
        # Instantiate Components
        self.sender = Sender(name="sender", parent=self, 
                             total_packets=args.total_packets, 
                             timeout=args.timeout, 
                             sender_delay=args.sender_delay)
        
        self.receiver = Receiver(name="receiver", parent=self, 
                                 receiver_delay=args.receiver_delay)
        
        self.subnet1 = Subnet(name="subnet1", parent=self, 
                              channel_delay=args.channel_delay, 
                              seed=args.seed, 
                              channel_id="forward")
        
        self.subnet2 = Subnet(name="subnet2", parent=self, 
                              channel_delay=args.channel_delay, 
                              seed=args.seed, 
                              channel_id="backward")
        
        # Add Components
        self.add_component(self.sender)
        self.add_component(self.receiver)
        self.add_component(self.subnet1)
        self.add_component(self.subnet2)
        
        # Couplings
        # Sender -> Subnet1
        self.add_coupling(self.sender.packet_out, self.subnet1.packet_in)
        
        # Subnet1 -> Receiver
        self.add_coupling(self.subnet1.packet_out, self.receiver.packet_in)
        
        # Receiver -> Subnet2
        self.add_coupling(self.receiver.ack_out, self.subnet2.packet_in)
        
        # Subnet2 -> Sender
        self.add_coupling(self.subnet2.packet_out, self.sender.ack_in)


# --- Main Entry Point ---

def main():
    parser = argparse.ArgumentParser(description="Reliable Data Transfer Simulation")
    parser.add_argument("--total_packets", type=int, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--sender_delay", type=int, default=10)
    parser.add_argument("--receiver_delay", type=int, default=10)
    parser.add_argument("--channel_delay", type=int, default=3)
    parser.add_argument("--simulate_time", type=int, default=1000)
    
    args = parser.parse_args()
    
    # Create System
    root = ReliableSystem(name="system", parent=None, args=args)
    
    # Create Coordinator
    # Note: SimulationClock(0) means no real-time constraint, run as fast as possible
    coord = Coordinator(root, clock=SimulationClock(0))
    
    # Initialize
    coord.initialize()
    
    # Simulate
    coord.simulate_time(args.simulate_time)

if __name__ == "__main__":
    main()