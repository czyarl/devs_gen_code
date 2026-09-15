import argparse
import sys
import json
import logging
import simpy

# Setup logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

def print_event(time, entity, event, payload):
    """
    Prints a JSONL event to stdout.
    """
    record = {
        "time": round(float(time), 2),
        "entity": entity,
        "event": event,
        "payload": payload
    }
    print(json.dumps(record))
    sys.stdout.flush()

class Subnet:
    def __init__(self, env, direction, channel_delay, seed, dest_store):
        self.env = env
        self.direction = direction # "forward" or "backward"
        self.channel_delay = channel_delay
        self.noise_level = seed
        self.dest_store = dest_store

    def put(self, packet):
        """Receives a packet and starts processing."""
        self.env.process(self._process(packet))

    def _process(self, packet):
        # 1. Determine Fate immediately upon arrival
        new_noise = (17 * self.noise_level + 11) % 100
        is_dropped = new_noise < 10
        behavior = "drop" if is_dropped else "pass"
        
        # Log event
        print_event(
            time=self.env.now,
            entity="subnet",
            event="packet_get",
            payload={
                "behavior": behavior,
                "channel": self.direction,
                "noise_value": new_noise
            }
        )
        
        # Update noise level
        self.noise_level = new_noise
        
        if not is_dropped:
            # 2. Transmission delay
            yield self.env.timeout(self.channel_delay)
            
            # 3. Deliver to destination
            # Check capacity to ensure non-blocking behavior for the subnet process
            # If destination is full, packet is discarded
            if len(self.dest_store.items) < self.dest_store.capacity:
                self.dest_store.put(packet)

class Sender:
    def __init__(self, env, total_packets, timeout, sender_delay, subnet, ack_store):
        self.env = env
        self.total_packets = total_packets
        self.timeout = timeout
        self.sender_delay = sender_delay
        self.subnet = subnet
        self.ack_store = ack_store
        
        self.seq_num = 0
        self.current_bit = 0
        self.packets_sent_count = 0
        self.waiting_for_ack = False

    def start(self):
        self.env.process(self.run())

    def run(self):
        while self.packets_sent_count < self.total_packets:
            # 1. Preparation Delay
            print_event(
                time=self.env.now,
                entity="sender",
                event="delay_start",
                payload={"type": "preparation", "duration": self.sender_delay}
            )
            yield self.env.timeout(self.sender_delay)
            
            # 2. Send Packet
            is_retry = self.waiting_for_ack
            packet = {
                "seq_num": self.seq_num + 1,
                "bit": self.current_bit
            }
            
            print_event(
                time=self.env.now,
                entity="sender",
                event="packet_sent",
                payload={
                    "seq_num": packet["seq_num"],
                    "bit": packet["bit"],
                    "is_retry": is_retry
                }
            )
            
            self.subnet.put(packet)
            
            if not self.waiting_for_ack:
                self.waiting_for_ack = True
            
            # 3. Wait for ACK
            while self.waiting_for_ack:
                try:
                    ack = yield self.ack_store.get(timeout=self.timeout)
                    is_valid = (ack["bit"] == self.current_bit)
                    
                    print_event(
                        time=self.env.now,
                        entity="sender",
                        event="ack_received",
                        payload={"ack_bit": ack["bit"], "is_valid": is_valid}
                    )
                    
                    if is_valid:
                        self.packets_sent_count += 1
                        self.seq_num += 1
                        self.current_bit = 1 - self.current_bit
                        self.waiting_for_ack = False
                    # else: Invalid ACK, continue waiting (ignore)
                        
                except simpy.events.Timeout:
                    # Timeout expired, break inner loop to retransmit
                    break

class Receiver:
    def __init__(self, env, receiver_delay, subnet, packet_store):
        self.env = env
        self.receiver_delay = receiver_delay
        self.subnet = subnet
        self.packet_store = packet_store
        self.current_bit = 0 # Expected bit
        
        self.env.process(self.run())

    def run(self):
        while True:
            # Wait for packet
            packet = yield self.packet_store.get()
            
            # Processing Delay
            print_event(
                time=self.env.now,
                entity="receiver",
                event="delay_start",
                payload={"type": "processing", "duration": self.receiver_delay}
            )
            yield self.env.timeout(self.receiver_delay)
            
            # Packet Received
            print_event(
                time=self.env.now,
                entity="receiver",
                event="packet_received",
                payload={"seq_num": packet["seq_num"], "bit": packet["bit"]}
            )
            
            # Send ACK
            ack = {"bit": packet["bit"]}
            self.subnet.put(ack)

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
    
    # Initialize Environment
    env = simpy.Environment()
    
    # Create Stores
    # Receiver packet buffer (capacity 1)
    receiver_packet_store = simpy.Store(env, capacity=1)
    # Sender ACK buffer
    sender_ack_store = simpy.Store(env)
    
    # Create Subnets
    # Subnet1: Sender -> Receiver (Forward)
    subnet1 = Subnet(env, "forward", args.channel_delay, args.seed, receiver_packet_store)
    # Subnet2: Receiver -> Sender (Backward)
    subnet2 = Subnet(env, "backward", args.channel_delay, args.seed, sender_ack_store)
    
    # Create Entities
    sender = Sender(env, args.total_packets, args.timeout, args.sender_delay, subnet1, sender_ack_store)
    receiver = Receiver(env, args.receiver_delay, subnet2, receiver_packet_store)
    
    # Start Simulation
    sender.start()
    
    env.run(until=args.simulate_time)

if __name__ == "__main__":
    main()