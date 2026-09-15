import argparse
import sys
import json
import simpy
import logging

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

class Packet:
    def __init__(self, seq_num, bit):
        self.seq_num = seq_num
        self.bit = bit

class Ack:
    def __init__(self, bit):
        self.bit = bit

def log_event(env, entity, event, payload):
    """Helper function to print JSONL events to stdout."""
    record = {
        "time": round(env.now, 2),
        "entity": entity,
        "event": event,
        "payload": payload
    }
    sys.stdout.write(json.dumps(record) + "\n")
    sys.stdout.flush()

def subnet_process(env, name, in_queue, out_queue, delay, seed, direction):
    """
    Simulates a subnet channel with deterministic noise.
    """
    x = seed
    while True:
        pkt = yield in_queue.get()
        
        # Noise calculation
        x_new = (17 * x + 11) % 100
        behavior = "drop" if x_new < 10 else "pass"
        
        log_event(env, "subnet", "packet_get", {
            "behavior": behavior,
            "channel": direction,
            "noise_value": x_new
        })
        
        x = x_new
        
        if behavior == "drop":
            continue
            
        yield env.timeout(delay)
        
        # Deliver to output
        # Check if output queue (Receiver buffer) has capacity and is full
        if hasattr(out_queue, 'capacity') and out_queue.capacity is not None:
            if len(out_queue.items) >= out_queue.capacity:
                # Buffer full, drop packet (simulating loss at receiver interface)
                continue
        
        yield out_queue.put(pkt)

def sender_process(env, args, out_queue, in_queue):
    """
    Simulates the Sender entity using Alternating Bit Protocol.
    """
    seq_num = 1
    current_bit = 0
    total_packets = args.total_packets
    
    while seq_num <= total_packets:
        # 1. Preparation Delay
        log_event(env, "sender", "delay_start", {
            "type": "preparation", 
            "duration": float(args.sender_delay)
        })
        yield env.timeout(args.sender_delay)
        
        # 2. Send Packet Logic
        is_retry = False
        sent_current = False
        
        # Timer Process
        def timer_handler():
            yield env.timeout(args.timeout)
        
        timer_proc = env.process(timer_handler())
        
        while True:
            if not sent_current:
                log_event(env, "sender", "packet_sent", {
                    "seq_num": seq_num,
                    "bit": current_bit,
                    "is_retry": is_retry
                })
                yield out_queue.put(Packet(seq_num, current_bit))
                sent_current = True
                is_retry = True
            
            # Wait for ACK or Timeout
            ack_event = in_queue.get()
            
            # Wait for either event
            yield ack_event | timer_proc
            
            if not timer_proc.is_alive:
                # Timeout occurred
                break # Break inner loop to retransmit
            else:
                # ACK Received
                ack = ack_event.value
                
                log_event(env, "sender", "ack_received", {
                    "ack_bit": ack.bit,
                    "is_valid": (ack.bit == current_bit)
                })
                
                if ack.bit == current_bit:
                    # Valid ACK
                    # Stop timer
                    timer_proc.interrupt()
                    seq_num += 1
                    current_bit = 1 - current_bit
                    break # Break inner loop to send next packet
                else:
                    # Invalid ACK
                    # Continue waiting (timer is still running)
                    pass

def receiver_process(env, args, in_queue, out_queue):
    """
    Simulates the Receiver entity.
    """
    while True:
        # Wait for packet in buffer
        pkt = yield in_queue.get()
        
        # Processing Delay
        log_event(env, "receiver", "delay_start", {
            "type": "processing",
            "duration": float(args.receiver_delay)
        })
        yield env.timeout(args.receiver_delay)
        
        # Packet Received
        log_event(env, "receiver", "packet_received", {
            "seq_num": pkt.seq_num,
            "bit": pkt.bit
        })
        
        # Send ACK
        yield out_queue.put(Ack(pkt.bit))

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
    
    env = simpy.Environment()
    
    # Queues
    # Sender -> Subnet1
    q_sender_to_subnet1 = simpy.Store(env)
    # Subnet1 -> Receiver (Buffer with capacity 1)
    q_buffer = simpy.Store(env, capacity=1)
    # Receiver -> Subnet2
    q_receiver_to_subnet2 = simpy.Store(env)
    # Subnet2 -> Sender
    q_subnet2_to_sender = simpy.Store(env)
    
    # Processes
    env.process(subnet_process(env, "Subnet1", q_sender_to_subnet1, q_buffer, args.channel_delay, args.seed, "forward"))
    env.process(subnet_process(env, "Subnet2", q_receiver_to_subnet2, q_subnet2_to_sender, args.channel_delay, args.seed, "backward"))
    
    env.process(sender_process(env, args, q_sender_to_subnet1, q_subnet2_to_sender))
    env.process(receiver_process(env, args, q_buffer, q_receiver_to_subnet2))
    
    env.run(until=args.simulate_time)

if __name__ == "__main__":
    main()