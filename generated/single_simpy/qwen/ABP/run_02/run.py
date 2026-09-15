import argparse
import sys
import json
import logging
import random
import simpy
from collections import deque

# Configure logging to stderr
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(message)s')

class Packet:
    def __init__(self, seq_num, bit):
        self.seq_num = seq_num
        self.bit = bit

class ACKPacket:
    def __init__(self, bit):
        self.bit = bit

class EventLogger:
    def __init__(self):
        self.events = []
    
    def log(self, time, entity, event, payload):
        self.events.append({
            "time": round(float(time), 2),
            "entity": entity,
            "event": event,
            "payload": payload
        })
    
    def flush(self):
        for event in self.events:
            print(json.dumps(event))
        self.events = []

class Subnet:
    def __init__(self, env, name, channel_delay, seed):
        self.env = env
        self.name = name
        self.channel_delay = channel_delay
        self.x = seed
        self.out_queue = simpy.Store(env)
        self.packet_count = 0
        
    def process_packet(self, packet):
        # Calculate new noise level
        self.x = (17 * self.x + 11) % 100
        noise_value = self.x
        
        # Determine if packet is dropped
        if noise_value < 10:
            behavior = "drop"
            # Log packet drop event
            event_logger.log(self.env.now, "subnet", "packet_get", {
                "behavior": behavior,
                "channel": self.name,
                "noise_value": noise_value
            })
            return None
        else:
            behavior = "pass"
            # Log packet pass event
            event_logger.log(self.env.now, "subnet", "packet_get", {
                "behavior": behavior,
                "channel": self.name,
                "noise_value": noise_value
            })
            
            # Simulate transmission delay
            yield self.env.timeout(self.channel_delay)
            
            # Return packet for delivery
            return packet

class Sender:
    def __init__(self, env, total_packets, sender_delay, timeout, subnet1):
        self.env = env
        self.total_packets = total_packets
        self.sender_delay = sender_delay
        self.timeout = timeout
        self.subnet1 = subnet1
        self.seq_num = 1
        self.bit = 0
        self.timer = None
        self.waiting_for_ack = False
        self.retransmissions = 0
        self.is_running = True
        
    def run(self):
        while self.is_running and self.seq_num <= self.total_packets:
            # Prepare for packet transmission
            event_logger.log(self.env.now, "sender", "delay_start", {
                "type": "preparation",
                "duration": self.sender_delay
            })
            yield self.env.timeout(self.sender_delay)
            
            # Create packet
            packet = Packet(self.seq_num, self.bit)
            
            # Send packet
            event_logger.log(self.env.now, "sender", "packet_sent", {
                "seq_num": packet.seq_num,
                "bit": packet.bit,
                "is_retry": self.retransmissions > 0
            })
            
            # Start timer
            self.timer = self.env.timeout(self.timeout)
            self.waiting_for_ack = True
            self.retransmissions = 0
            
            # Send packet to subnet
            yield self.subnet1.out_queue.put(packet)
            
            # Wait for ACK or timeout
            try:
                yield self.timer
                # Timeout occurred
                self.retransmissions += 1
                # Restart timer and retransmit
                event_logger.log(self.env.now, "sender", "delay_start", {
                    "type": "preparation",
                    "duration": self.sender_delay
                })
                yield self.env.timeout(self.sender_delay)
                packet = Packet(self.seq_num, self.bit)
                event_logger.log(self.env.now, "sender", "packet_sent", {
                    "seq_num": packet.seq_num,
                    "bit": packet.bit,
                    "is_retry": True
                })
                yield self.subnet1.out_queue.put(packet)
                self.timer = self.env.timeout(self.timeout)
                yield self.timer
                # If still timeout, we assume the connection is dead
                self.is_running = False
                break
            except simpy.Interrupt:
                # Received ACK
                pass
                
            # Move to next packet
            self.seq_num += 1
            self.bit = 1 - self.bit  # Alternate bit
            self.waiting_for_ack = False
            
        if self.seq_num > self.total_packets:
            self.is_running = False

class Receiver:
    def __init__(self, env, receiver_delay, subnet2):
        self.env = env
        self.receiver_delay = receiver_delay
        self.subnet2 = subnet2
        self.buffer = deque(maxlen=1)
        self.processing = False
        
    def run(self):
        while True:
            # Wait for packet
            packet = yield self.subnet2.out_queue.get()
            
            # Process packet
            event_logger.log(self.env.now, "receiver", "delay_start", {
                "type": "processing",
                "duration": self.receiver_delay
            })
            yield self.env.timeout(self.receiver_delay)
            
            # Log packet received
            event_logger.log(self.env.now, "receiver", "packet_received", {
                "seq_num": packet.seq_num,
                "bit": packet.bit
            })
            
            # Send ACK
            ack = ACKPacket(packet.bit)
            event_logger.log(self.env.now, "receiver", "delay_start", {
                "type": "processing",
                "duration": self.receiver_delay
            })
            yield self.env.timeout(self.receiver_delay)
            yield self.subnet2.out_queue.put(ack)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--total_packets', type=int, required=True)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--timeout', type=int, default=20)
    parser.add_argument('--sender_delay', type=int, default=10)
    parser.add_argument('--receiver_delay', type=int, default=10)
    parser.add_argument('--channel_delay', type=int, default=3)
    parser.add_argument('--simulate_time', type=int, default=1000)
    
    args = parser.parse_args()
    
    # Initialize simulation environment
    env = simpy.Environment()
    
    # Create subnets with specified delay and seed
    subnet1 = Subnet(env, "forward", args.channel_delay, args.seed)
    subnet2 = Subnet(env, "backward", args.channel_delay, args.seed)
    
    # Create entities
    sender = Sender(env, args.total_packets, args.sender_delay, args.timeout, subnet1)
    receiver = Receiver(env, args.receiver_delay, subnet2)
    
    # Start processes
    env.process(sender.run())
    env.process(receiver.run())
    
    # Run simulation
    env.run(until=args.simulate_time)
    
    # Flush any remaining logs
    event_logger.flush()

if __name__ == "__main__":
    event_logger = EventLogger()
    main()