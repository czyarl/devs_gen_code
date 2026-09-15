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

# Data Structure for Packets
class Packet:
    def __init__(self, seq, bit):
        self.seq = seq
        self.bit = bit

# Helper to log events to stdout
def log_event(timestamp_ms, model, event_type, val):
    output = {
        "timestamp_ms": timestamp_ms,
        "model": model,
        "type": event_type,
        "val": val
    }
    print(json.dumps(output))
    sys.stdout.flush()

# Helper to parse time string HH:MM:SS:mmm or HH:MM:SS
def parse_time(time_str):
    parts = time_str.split(':')
    h = int(parts[0])
    m = int(parts[1])
    if len(parts) == 4:
        s = int(parts[2])
        ms = int(parts[3])
    else:
        s = int(parts[2])
        ms = 0
    return h * 3600000 + m * 60000 + s * 1000 + ms

# Subnet Process
def subnet_process(env, name, in_queue, out_queue, delay_ms):
    while True:
        packet = yield in_queue.get()
        yield env.timeout(delay_ms)
        yield out_queue.put(packet)

# Sender Process
def sender_process(env, control_queue, out_a1, in_a2, storage_queue):
    packets_remaining = 0
    current_seq = 1
    current_bit = 0
    current_packet = None
    
    def send_packet(is_retry):
        nonlocal current_packet
        p = Packet(seq=current_seq, bit=current_bit)
        current_packet = p
        log_event(env.now, "sender", "packet_sent", {"seq": p.seq, "bit": p.bit, "is_retry": is_retry})
        return out_a1.put(p)

    while True:
        # If idle, wait for control
        if packets_remaining == 0:
            cmd = yield control_queue.get()
            packets_remaining += cmd['value']
            log_event(env.now, "sender", "control_cmd", {"added": cmd['value'], "total_remaining": packets_remaining})
        
        # If we have work, start the cycle
        if packets_remaining > 0:
            # Preparation
            log_event(env.now, "sender", "preparation_started", {"duration": 10000})
            yield env.timeout(10000)
            
            # ABP Loop
            while packets_remaining > 0:
                # Check for any new control commands that arrived during prep or waiting
                # (Drain queue to update remaining count)
                while not control_queue.empty():
                    try:
                        cmd = yield control_queue.get()
                        packets_remaining += cmd['value']
                        log_event(env.now, "sender", "control_cmd", {"added": cmd['value'], "total_remaining": packets_remaining})
                    except:
                        break
                
                # Send packet
                yield send_packet(is_retry=False)
                
                # Wait for ACK
                ack_received = False
                while not ack_received:
                    try:
                        ack = yield in_a2.get(timeout=20000)
                        if ack.bit == current_bit:
                            log_event(env.now, "sender", "ack_received", {"bit": ack.bit})
                            ack_received = True
                            current_bit = 1 - current_bit
                            current_seq += 1
                            packets_remaining -= 1
                            current_packet = None
                        # else: duplicate ACK, ignore
                    except simpy.events.Timeout:
                        log_event(env.now, "sender", "timeout", {"seq": current_seq})
                        yield send_packet(is_retry=True)

# ServerReceiver Process
def server_receiver_process(env, in_a1, out_a2, storage_queue):
    expected_bit = 0
    while True:
        packet = yield in_a1.get()
        log_event(env.now, "server_receiver", "packet_received", {"seq": packet.seq, "bit": packet.bit})
        
        yield env.timeout(3000) # Processing delay
        
        if packet.bit == expected_bit:
            log_event(env.now, "server_receiver", "ack_sent_to_sender", {"bit": packet.bit})
            yield out_a2.put(Packet(seq=packet.seq, bit=packet.bit))
            yield storage_queue.put(packet)
            expected_bit = 1 - expected_bit
        else:
            # Duplicate
            log_event(env.now, "server_receiver", "ack_sent_to_sender", {"bit": packet.bit})
            yield out_a2.put(Packet(seq=packet.seq, bit=packet.bit))

# ServerSender Process
def server_sender_process(env, request_queue, storage_queue, out_b1, in_b2):
    download_allowed = False
    current_seq = 1
    current_bit = 0
    current_packet = None
    
    def send_packet(p):
        nonlocal current_packet
        current_packet = p
        log_event(env.now, "server_sender", "packet_forwarded", {"seq": p.seq, "bit": p.bit})
        return out_b1.put(p)

    while True:
        # Drain request queue to update flag
        while not request_queue.empty():
            try:
                req = yield request_queue.get()
                download_allowed = (req['value'] == 1)
                log_event(env.now, "server_sender", "download_valve_change", {"allowed": download_allowed})
            except:
                break
        
        if download_allowed and not storage_queue.empty() and current_packet is None:
            # Get packet from storage
            # Note: We create a new packet with ServerSender's own ABP sequence
            payload_packet = yield storage_queue.get()
            p = Packet(seq=current_seq, bit=current_bit)
            
            yield send_packet(p)
            
            # Wait for ACK
            ack_received = False
            while not ack_received:
                try:
                    ack = yield in_b2.get(timeout=20000)
                    if ack.bit == current_bit:
                        log_event(env.now, "server_sender", "ack_received_from_receiver", {"bit": ack.bit})
                        ack_received = True
                        current_bit = 1 - current_bit
                        current_seq += 1
                        current_packet = None
                except simpy.events.Timeout:
                    yield send_packet(p)
        else:
            # Wait a bit to check again (polling)
            yield env.timeout(100)

# Receiver Process
def receiver_process(env, in_b1, out_b2):
    expected_bit = 0
    while True:
        packet = yield in_b1.get()
        log_event(env.now, "receiver", "processing_started", {"seq": packet.seq, "duration": 10000})
        
        yield env.timeout(10000)
        
        log_event(env.now, "receiver", "ack_sent", {"bit": packet.bit})
        yield out_b2.put(Packet(seq=packet.seq, bit=packet.bit))

# Input Handler
def input_handler(env, control_queue, request_queue):
    for line in sys.stdin:
        line = line.strip()
        if not line: continue
        parts = line.split()
        if len(parts) < 3: continue
        
        time_str = parts[0]
        cmd_type = parts[1]
        val = parts[2]
        
        target_time = parse_time(time_str)
        
        # Schedule the event
        def event_wrapper(t, c, v):
            yield env.timeout(t - env.now)
            if c == 'control':
                yield control_queue.put({'value': int(v)})
            elif c == 'request':
                yield request_queue.put({'value': int(v)})
        
        env.process(event_wrapper(target_time, cmd_type, val))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulation_time', type=float, default=10000000.0)
    args = parser.parse_args()
    
    env = simpy.Environment()
    
    # Queues
    control_queue = simpy.Store(env)
    request_queue = simpy.Store(env)
    
    # Subnet A
    a1_in = simpy.Store(env)
    a1_out = simpy.Store(env)
    a2_in = simpy.Store(env)
    a2_out = simpy.Store(env)
    
    # Subnet B
    b1_in = simpy.Store(env)
    b1_out = simpy.Store(env)
    b2_in = simpy.Store(env)
    b2_out = simpy.Store(env)
    
    # Storage
    storage_queue = simpy.Store(env)
    
    # Start Subnets
    env.process(subnet_process(env, "A1", a1_in, a1_out, 3000))
    env.process(subnet_process(env, "A2", a2_in, a2_out, 3000))
    env.process(subnet_process(env, "B1", b1_in, b1_out, 3000))
    env.process(subnet_process(env, "B2", b2_in, b2_out, 3000))
    
    # Start Entities
    env.process(sender_process(env, control_queue, a1_in, a2_out, storage_queue))
    env.process(server_receiver_process(env, a1_out, a2_in, storage_queue))
    env.process(server_sender_process(env, request_queue, storage_queue, b1_in, b2_out))
    env.process(receiver_process(env, b1_out, b2_in))
    
    # Start Input Handler
    env.process(input_handler(env, control_queue, request_queue))
    
    # Run
    env.run(until=args.simulation_time)

if __name__ == "__main__":
    main()