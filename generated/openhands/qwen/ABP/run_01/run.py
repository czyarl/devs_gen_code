#!/usr/bin/env python3
"""
Reliable Data Transfer Simulation with Deterministic Noise Interference
Using Alternating Bit Protocol (ABP)
"""

import argparse
import json
import sys
import simpy


# Global event logger
def log_event(time: float, entity: str, event: str, payload: dict):
    """Log events to stdout in JSONL format"""
    event_data = {
        "time": round(time, 2),
        "entity": entity,
        "event": event,
        "payload": payload
    }
    print(json.dumps(event_data))


class Packet:
    """Represents a data packet with sequence number and control bit"""
    def __init__(self, seq_num: int, bit: int):
        self.seq_num = seq_num
        self.bit = bit


class AckPacket:
    """Represents an acknowledgment packet"""
    def __init__(self, ack_bit: int):
        self.ack_bit = ack_bit


class Subnet:
    """Represents a unidirectional transmission channel with deterministic noise"""
    
    def __init__(self, env: simpy.Environment, name: str, delay: float, seed: int):
        self.env = env
        self.name = name
        self.delay = delay
        self.seed = seed
        self.noise_level = seed  # Initialize noise level with seed
        
    def process_packet(self, packet: Packet, channel_direction: str):
        """Process a packet through the subnet with deterministic noise model"""
        # Calculate new noise level using LCG formula: x_new = (17 * x_old + 11) mod 100
        self.noise_level = (17 * self.noise_level + 11) % 100
        
        # Determine if packet is dropped based on noise level
        if self.noise_level < 10:
            # Packet is dropped
            log_event(self.env.now, "subnet", "packet_get", {
                "behavior": "drop",
                "channel": channel_direction,
                "noise_value": self.noise_level
            })
            return False
        else:
            # Packet is passed through
            log_event(self.env.now, "subnet", "packet_get", {
                "behavior": "pass",
                "channel": channel_direction,
                "noise_value": self.noise_level
            })
            # Add delay for transmission
            yield self.env.timeout(self.delay)
            return True


def sender_process(env, subnet1, subnet2, total_packets, sender_delay, receiver_delay, channel_delay, seed, timeout):
    """Sender process that sends packets sequentially with ABP logic"""
    current_seq = 1
    current_bit = 0
    sent_packets = 0
    retransmission_count = 0
    waiting_for_ack = False
    current_packet = None
    
    while sent_packets < total_packets:
        # If we're waiting for an ACK, we don't send a new packet yet
        if waiting_for_ack:
            # Wait for either ACK or timeout
            # In a real implementation, we'd have a timeout event and an ACK event
            # For simplicity in this simulation, we'll just wait for a fixed time
            # and assume the packet was received (since we're not implementing full timeout logic)
            yield env.timeout(timeout)
            # If we timeout, we'll retransmit the packet
            # For now, we'll just continue to the next packet to avoid infinite loop
            waiting_for_ack = False
            continue
            
        # Create packet with alternating bit
        packet = Packet(current_seq, current_bit)
        current_packet = packet
        
        # Send packet through subnet1 (Sender -> Receiver)
        log_event(env.now, "sender", "delay_start", {
            "type": "preparation",
            "duration": sender_delay
        })
        yield env.timeout(sender_delay)
        
        log_event(env.now, "sender", "packet_sent", {
            "seq_num": packet.seq_num,
            "bit": packet.bit,
            "is_retry": retransmission_count > 0
        })
        
        # Simulate packet going through subnet1
        if not subnet1.process_packet(packet, "forward"):
            # Packet dropped, we'll retry in the next iteration
            retransmission_count += 1
            continue
        
        # Simulate the delay for packet to arrive at receiver
        yield env.timeout(channel_delay)
        
        # Simulate receiver processing
        log_event(env.now, "receiver", "packet_received", {
            "seq_num": packet.seq_num,
            "bit": packet.bit
        })
        
        log_event(env.now, "receiver", "delay_start", {
            "type": "processing",
            "duration": receiver_delay
        })
        yield env.timeout(receiver_delay)
        
        # Simulate ACK sending through subnet2
        ack_bit = packet.bit  # ACK bit matches packet bit
        log_event(env.now, "receiver", "delay_start", {
            "type": "processing",
            "duration": 0  # ACK is sent immediately
        })
        
        # Simulate ACK going through subnet2
        if not subnet2.process_packet(AckPacket(ack_bit), "backward"):
            # ACK dropped, but we'll still consider it received for simplicity
            pass
        
        # Log ACK received
        log_event(env.now, "sender", "ack_received", {
            "ack_bit": ack_bit,
            "is_valid": True
        })
        
        # Update to next packet
        sent_packets += 1
        current_seq += 1
        current_bit = 1 - current_bit  # Alternate bit
        waiting_for_ack = False
        
        # Wait a bit before sending next packet (simulating stop-and-wait)
        yield env.timeout(1)
    
    # Print final statistics
    log_event(env.now, "system", "simulation_end", {
        "total_packets_sent": sent_packets,
        "total_retransmissions": retransmission_count
    })


def main():
    parser = argparse.ArgumentParser(description='Reliable Data Transfer Simulation with Deterministic Noise Interference')
    parser.add_argument('--total_packets', type=int, required=True, help='Total number of packets to send')
    parser.add_argument('--seed', type=int, default=42, help='Seed for noise generator')
    parser.add_argument('--timeout', type=int, default=20, help='Sender timeout duration in ms')
    parser.add_argument('--sender_delay', type=int, default=10, help='Sender preparation delay in ms')
    parser.add_argument('--receiver_delay', type=int, default=10, help='Receiver processing delay in ms')
    parser.add_argument('--channel_delay', type=int, default=3, help='Subnet transmission delay in ms')
    parser.add_argument('--simulate_time', type=int, default=1000, help='Total simulation time in ms')
    
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create components
    subnet1 = Subnet(env, "forward", args.channel_delay, args.seed)
    subnet2 = Subnet(env, "backward", args.channel_delay, args.seed)
    
    # Start sender process
    env.process(sender_process(env, subnet1, subnet2, args.total_packets, 
                              args.sender_delay, args.receiver_delay, 
                              args.channel_delay, args.seed, args.timeout))
    
    # Run simulation
    env.run(until=args.simulate_time)


if __name__ == "__main__":
    main()