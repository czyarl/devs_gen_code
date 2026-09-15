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

class Subnet:
    def __init__(self, env, name, delay, seed):
        self.env = env
        self.name = name
        self.delay = delay
        self.x = seed
        self.packet_queue = deque()
        self.is_busy = False

    def process_packet(self, packet, destination):
        # Determine packet fate
        new_x = (17 * self.x + 11) % 100
        self.x = new_x
        
        # Record packet fate
        if new_x < 10:
            # Drop packet
            yield self.env.timeout(0)
            self.packet_queue.append(("drop", packet, destination))
            logging.debug(f"Subnet {self.name}: Packet {packet.seq_num} dropped (noise={new_x})")
        else:
            # Pass packet
            yield self.env.timeout(self.delay)
            self.packet_queue.append(("pass", packet, destination))
            logging.debug(f"Subnet {self.name}: Packet {packet.seq_num} passed (noise={new_x})")
        
        # Process queue
        while self.packet_queue:
            action, pkt, dest = self.packet_queue.popleft()
            if action == "pass":
                dest.receive_packet(pkt)
            elif action == "drop":
                pass  # Packet dropped

    def send_packet(self, packet, destination):
        # Start processing the packet
        self.env.process(self.process_packet(packet, destination))

class Sender:
    def __init__(self, env, total_packets, timeout, delay, subnet1):
        self.env = env
        self.total_packets = total_packets
        self.timeout = timeout
        self.delay = delay
        self.subnet1 = subnet1
        self.seq_num = 1
        self.bit = 0
        self.timer = None
        self.is_waiting_for_ack = False
        self.packet_sent = 0
        self.retransmissions = 0
        
    def send_packets(self):
        while self.packet_sent < self.total_packets:
            # Start preparation delay
            yield self.env.timeout(self.delay)
            logging.debug(f"Sender: Starting preparation for packet {self.seq_num}")
            self.log_event("sender", "delay_start", {"type": "preparation", "duration": self.delay})
            
            # Create packet
            packet = Packet(self.seq_num, self.bit)
            
            # Send packet
            logging.debug(f"Sender: Sending packet {self.seq_num} with bit {self.bit}")
            self.log_event("sender", "packet_sent", {"seq_num": self.seq_num, "bit": self.bit, "is_retry": self.is_waiting_for_ack})
            self.subnet1.send_packet(packet, self)
            
            # Set timer
            self.timer = self.env.timeout(self.timeout)
            self.is_waiting_for_ack = True
            
            # Wait for ACK or timeout
            try:
                yield self.timer
                # Timeout occurred
                logging.debug(f"Sender: Timeout for packet {self.seq_num}")
                # Retransmit
                self.retransmissions += 1
                self.seq_num -= 1  # Retransmit same packet
                self.bit = 1 - self.bit  # Toggle bit
            except simpy.Interrupt:
                # ACK received
                pass
            
            # Move to next packet
            self.seq_num += 1
            self.bit = 1 - self.bit  # Toggle bit
            self.packet_sent += 1
            self.is_waiting_for_ack = False
            
    def receive_ack(self, ack):
        if self.is_waiting_for_ack:
            # Cancel timer
            self.timer.interrupt()
            # Check if ACK is valid
            is_valid = (ack.bit == self.bit)
            logging.debug(f"Sender: Received ACK with bit {ack.bit}, expected {self.bit}, valid: {is_valid}")
            self.log_event("sender", "ack_received", {"ack_bit": ack.bit, "is_valid": is_valid})
            if is_valid:
                # Valid ACK, continue with next packet
                pass
            else:
                # Invalid ACK, retransmit
                self.seq_num -= 1
                self.bit = 1 - self.bit
                self.packet_sent -= 1
                self.is_waiting_for_ack = True
                
    def log_event(self, entity, event, payload):
        event_data = {
            "time": self.env.now,
            "entity": entity,
            "event": event,
            "payload": payload
        }
        print(json.dumps(event_data))

class Receiver:
    def __init__(self, env, delay, subnet2):
        self.env = env
        self.delay = delay
        self.subnet2 = subnet2
        self.buffer = None
        self.is_processing = False
        
    def receive_packet(self, packet):
        # Check if we're already processing
        if self.is_processing:
            # Buffer the packet
            self.buffer = packet
            logging.debug(f"Receiver: Packet {packet.seq_num} buffered")
        else:
            # Process immediately
            self.process_packet(packet)
            
    def process_packet(self, packet):
        self.is_processing = True
        # Start processing delay
        yield self.env.timeout(self.delay)
        logging.debug(f"Receiver: Processed packet {packet.seq_num} with bit {packet.bit}")
        self.log_event("receiver", "packet_received", {"seq_num": packet.seq_num, "bit": packet.bit})
        
        # Send ACK
        ack = ACKPacket(packet.bit)
        self.log_event("receiver", "delay_start", {"type": "processing", "duration": self.delay})
        self.subnet2.send_packet(ack, None)
        
        # Check if we have a buffered packet
        if self.buffer:
            packet = self.buffer
            self.buffer = None
            self.process_packet(packet)
        else:
            self.is_processing = False
            
    def log_event(self, entity, event, payload):
        event_data = {
            "time": self.env.now,
            "entity": entity,
            "event": event,
            "payload": payload
        }
        print(json.dumps(event_data))

def run_simulation(total_packets, seed, timeout, sender_delay, receiver_delay, channel_delay, simulate_time):
    # Create simulation environment
    env = simpy.Environment()
    
    # Create subnets
    subnet1 = Subnet(env, "forward", channel_delay, seed)
    subnet2 = Subnet(env, "backward", channel_delay, seed)
    
    # Create components
    sender = Sender(env, total_packets, timeout, sender_delay, subnet1)
    receiver = Receiver(env, receiver_delay, subnet2)
    
    # Connect components
    def forward_packet(packet):
        receiver.receive_packet(packet)
    
    def backward_packet(ack):
        sender.receive_ack(ack)
    
    # Set up subnet callbacks
    subnet1.packet_queue.appendleft(("pass", None, forward_packet))
    subnet2.packet_queue.appendleft(("pass", None, backward_packet))
    
    # Start simulation
    env.process(sender.send_packets())
    env.run(until=simulate_time)
    
    # Print final statistics
    logging.info(f"Simulation completed. Total packets sent: {total_packets}, Retransmissions: {sender.retransmissions}")

def main():
    parser = argparse.ArgumentParser(description="Reliable data transfer simulation")
    parser.add_argument("--total_packets", type=int, required=True, help="Total number of packets to send")
    parser.add_argument("--seed", type=int, default=42, help="Noise generator seed")
    parser.add_argument("--timeout", type=int, default=20, help="Sender timeout in ms")
    parser.add_argument("--sender_delay", type=int, default=10, help="Sender preparation delay in ms")
    parser.add_argument("--receiver_delay", type=int, default=10, help="Receiver processing delay in ms")
    parser.add_argument("--channel_delay", type=int, default=3, help="Subnet transmission delay in ms")
    parser.add_argument("--simulate_time", type=int, default=1000, help="Total simulation time in ms")
    
    args = parser.parse_args()
    
    # Run simulation
    run_simulation(
        args.total_packets,
        args.seed,
        args.timeout,
        args.sender_delay,
        args.receiver_delay,
        args.channel_delay,
        args.simulate_time
    )

if __name__ == "__main__":
    main()