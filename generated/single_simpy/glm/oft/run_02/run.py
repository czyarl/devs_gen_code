import argparse
import sys
import json
import logging
import simpy

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

# --- Data Structures ---

class Packet:
    def __init__(self, seq, bit):
        self.seq = seq
        self.bit = bit

class Ack:
    def __init__(self, bit):
        self.bit = bit

# --- Helper Functions ---

def log_event(env, model, event_type, val):
    """Prints a JSONL event to stdout."""
    event = {
        "timestamp_ms": round(env.now * 1000, 3),
        "model": model,
        "type": event_type,
        "val": val
    }
    print(json.dumps(event))
    sys.stdout.flush()

def parse_time_str(time_str):
    """
    Parses HH:MM:SS or HH:MM:SS:mmm into seconds (float).
    """
    parts = time_str.split(':')
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + int(s)
    elif len(parts) == 4:
        h, m, s, ms = parts
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0
    else:
        raise ValueError(f"Invalid time format: {time_str}")

# --- Simulation Processes ---

def subnet_process(env, name, in_store, out_store, delay):
    """
    Simulates a reliable, FIFO, fixed delay subnet.
    """
    while True:
        item = yield in_store.get()
        yield env.timeout(delay)
        yield out_store.put(item)

def sender_process(env, control_queue, out_a1, in_a2):
    """
    The Sender (Uploader).
    """
    packets_remaining = 0
    seq = 1
    bit = 0
    
    while True:
        # 1. Wait for work (Idle state)
        if packets_remaining <= 0:
            # Wait for control command
            cmd = yield control_queue.get()
            packets_remaining += cmd['value']
            log_event(env, "sender", "control_cmd", {
                "added": cmd['value'], 
                "total_remaining": packets_remaining
            })
            
            # If still 0 (e.g. control 0), continue waiting
            if packets_remaining <= 0:
                continue

        # 2. Preparation Phase
        log_event(env, "sender", "preparation_started", {"duration": 10000})
        yield env.timeout(10) # 10s preparation
        
        # 3. Send Loop (for current packet)
        # We retry until ACK is received
        is_retry = False
        
        while True:
            # Send Packet
            current_packet = Packet(seq, bit)
            yield out_a1.put(current_packet)
            log_event(env, "sender", "packet_sent", {
                "seq": seq, 
                "bit": bit, 
                "is_retry": is_retry
            })
            
            # Wait for ACK with Timeout
            ack_event = in_a2.get()
            timeout_event = env.timeout(20)
            result = yield ack_event | timeout_event
            
            if ack_event in result:
                # ACK Received
                ack = ack_event.value
                if ack.bit == bit:
                    # Correct ACK
                    log_event(env, "sender", "ack_received", {"bit": bit})
                    
                    # Update State
                    bit = 1 - bit
                    seq += 1
                    packets_remaining -= 1
                    is_retry = False
                    break # Exit retry loop, go back to check packets_remaining
                else:
                    # Wrong bit (old ACK), ignore and wait again
                    # We continue the inner while loop to wait for next event
                    continue
            else:
                # Timeout
                log_event(env, "sender", "timeout", {"seq": seq})
                is_retry = True
                # Loop back to send packet (retry)
                continue

        # Packet cycle complete.
        # Check for any pending control commands that arrived during transfer
        while len(control_queue.items) > 0:
            cmd = yield control_queue.get()
            packets_remaining += cmd['value']
            log_event(env, "sender", "control_cmd", {
                "added": cmd['value'], 
                "total_remaining": packets_remaining
            })

def server_receiver_process(env, in_a1, out_a2, storage_queue):
    """
    ServerReceiver (Ingress Logic).
    """
    expected_bit = 0
    
    while True:
        # Receive Data
        packet = yield in_a1.get()
        log_event(env, "server_receiver", "packet_received", {
            "seq": packet.seq, 
            "bit": packet.bit
        })
        
        # Processing delay: 3s
        yield env.timeout(3)
        
        # Logic
        if packet.bit == expected_bit:
            # Match
            yield out_a2.put(Ack(packet.bit))
            log_event(env, "server_receiver", "ack_sent_to_sender", {"bit": packet.bit})
            
            # Push to Storage
            yield storage_queue.put(packet)
            
            # Flip expected bit
            expected_bit = 1 - expected_bit
        else:
            # Mismatch (Duplicate)
            # Resend ACK(previous_bit)
            yield out_a2.put(Ack(packet.bit))
            log_event(env, "server_receiver", "ack_sent_to_sender", {"bit": packet.bit})

def server_sender_process(env, request_queue, storage_queue, out_b1, in_b2):
    """
    ServerSender (Egress Logic).
    """
    download_allowed = False
    current_packet = None
    
    while True:
        # 1. Process Request Updates
        while len(request_queue.items) > 0:
            cmd = yield request_queue.get()
            val = cmd['value']
            new_allowed = (val == 1)
            if download_allowed != new_allowed:
                download_allowed = new_allowed
                log_event(env, "server_sender", "download_valve_change", {"allowed": download_allowed})
        
        # 2. Send Logic
        if current_packet is None:
            # Not transferring. Check if we can start.
            if download_allowed and len(storage_queue.items) > 0:
                # Start Transfer
                packet = yield storage_queue.get()
                current_packet = packet
                
                # Send
                yield out_b1.put(packet)
                log_event(env, "server_sender", "packet_forwarded", {
                    "seq": packet.seq, 
                    "bit": packet.bit
                })
            else:
                # Wait a bit to poll queues
                yield env.timeout(0.1)
        else:
            # Transferring (Waiting for ACK)
            # Note: Prompt doesn't specify timeout for ServerSender.
            # We assume reliable channel or infinite wait.
            # To avoid deadlock if logic is wrong, we can use a long timeout or just wait.
            # Given Subnet is 3s, Receiver 10s, round trip is ~16s.
            # Let's wait indefinitely for ACK.
            
            ack = yield in_b2.get()
            
            if ack.bit == current_packet.bit:
                log_event(env, "server_sender", "ack_received_from_receiver", {"bit": ack.bit})
                current_packet = None # Cycle done
            else:
                # Wrong bit, keep waiting for correct one
                pass

def receiver_process(env, in_b1, out_b2):
    """
    The Receiver (Downloader).
    """
    while True:
        # Receive Data
        packet = yield in_b1.get()
        
        # Processing: 10s
        log_event(env, "receiver", "processing_started", {
            "seq": packet.seq, 
            "duration": 10000
        })
        yield env.timeout(10)
        
        # Send ACK
        yield out_b2.put(Ack(packet.bit))
        log_event(env, "receiver", "ack_sent", {"bit": packet.bit})

def input_scheduler(env, input_lines, control_queue, request_queue):
    """
    Parses input lines and schedules events into the queues.
    """
    events = []
    for line in input_lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        time_str = parts[0]
        cmd_type = parts[1]
        value = parts[2]
        
        try:
            t = parse_time_str(time_str)
            events.append((t, cmd_type, value))
        except ValueError:
            logger.warning(f"Skipping invalid line: {line}")
            continue
            
    events.sort(key=lambda x: x[0])
    
    for t, cmd_type, value in events:
        # Wait until the event time
        yield env.timeout(max(0, t - env.now))
        
        if cmd_type == "control":
            val_int = int(value)
            yield control_queue.put({"type": "control", "value": val_int})
        elif cmd_type == "request":
            val_int = int(value)
            yield request_queue.put({"type": "request", "value": val_int})

def main():
    parser = argparse.ArgumentParser(description="Dropbox-like Sync Simulation")
    parser.add_argument("--simulation_time", type=float, default=10000000.0, 
                        help="Simulation duration in milliseconds")
    args = parser.parse_args()
    
    # Read all stdin
    input_lines = sys.stdin.readlines()
    
    # Setup SimPy Environment
    env = simpy.Environment()
    
    # Setup Channels (Stores)
    # Subnet A
    store_a1_in = simpy.Store(env) 
    store_a1_out = simpy.Store(env) 
    store_a2_in = simpy.Store(env) 
    store_a2_out = simpy.Store(env) 
    
    # Subnet B
    store_b1_in = simpy.Store(env) 
    store_b1_out = simpy.Store(env) 
    store_b2_in = simpy.Store(env) 
    store_b2_out = simpy.Store(env) 
    
    # Internal Queues
    control_queue = simpy.Store(env) 
    request_queue = simpy.Store(env) 
    storage_queue = simpy.Store(env) 
    
    # Start Processes
    env.process(subnet_process(env, "A1", store_a1_in, store_a1_out, 3))
    env.process(subnet_process(env, "A2", store_a2_in, store_a2_out, 3))
    env.process(subnet_process(env, "B1", store_b1_in, store_b1_out, 3))
    env.process(subnet_process(env, "B2", store_b2_in, store_b2_out, 3))
    
    env.process(sender_process(env, control_queue, store_a1_in, store_a2_out))
    env.process(server_receiver_process(env, store_a1_out, store_a2_in, storage_queue))
    env.process(server_sender_process(env, request_queue, storage_queue, store_b1_in, store_b2_out))
    env.process(receiver_process(env, store_b1_out, store_b2_in))
    
    env.process(input_scheduler(env, input_lines, control_queue, request_queue))
    
    # Run
    sim_time_seconds = args.simulation_time / 1000.0
    logger.info(f"Starting simulation for {sim_time_seconds} seconds")
    env.run(until=sim_time_seconds)
    logger.info("Simulation finished")

if __name__ == "__main__":
    main()