import argparse
import json
import sys
import simpy

class SimulationLogger:
    @staticmethod
    def log(time, entity, event, payload):
        """
        Logs an event to stdout in JSONL format.
        """
        record = {
            "time": round(float(time), 2),
            "entity": entity,
            "event": event,
            "payload": payload
        }
        print(json.dumps(record), flush=True)

class Subnet:
    def __init__(self, env, name, delay, seed, destination_store):
        self.env = env
        self.name = name  # "forward" or "backward"
        self.delay = delay
        self.noise_x = seed
        self.dest = destination_store

    def put(self, packet):
        """
        Handles packet arrival, determines fate based on noise,
        and schedules transmission if passed.
        """
        # Deterministic noise calculation
        self.noise_x = (17 * self.noise_x + 11) % 100
        noise_val = self.noise_x
        
        is_drop = noise_val < 10
        
        # Log the fate determination immediately
        SimulationLogger.log(self.env.now, "subnet", "packet_get", {
            "behavior": "drop" if is_drop else "pass",
            "channel": self.name,
            "noise_value": noise_val
        })
        
        if not is_drop:
            self.env.process(self.transmit(packet))

    def transmit(self, packet):
        """
        Simulates transmission delay and delivers packet to destination.
        """
        yield self.env.timeout(self.delay)
        # Attempt to put into destination store.
        # If store is full (e.g., Receiver buffer full), packet is dropped.
        try:
            self.dest.put_nowait(packet)
        except:
            # Buffer full, packet lost silently as per requirements
            pass

class Receiver:
    def __init__(self, env, delay, backward_subnet):
        self.env = env
        self.delay = delay
        self.backward_subnet = backward_subnet
        # Buffer capacity 1
        self.inbox = simpy.Store(capacity=1)
        self.env.process(self.run())

    def run(self):
        while True:
            # Wait for packet to arrive in buffer
            packet = yield self.inbox.get()
            
            # Log processing start
            SimulationLogger.log(self.env.now, "receiver", "delay_start", {
                "type": "processing",
                "duration": float(self.delay)
            })
            
            # Undergo processing delay
            yield self.env.timeout(self.delay)
            
            # Log successful packet reception
            SimulationLogger.log(self.env.now, "receiver", "packet_received", {
                "seq_num": packet["seq_num"],
                "bit": packet["bit"]
            })
            
            # Send ACK back through backward subnet
            ack = {"type": "ack", "bit": packet["bit"]}
            self.backward_subnet.put(ack)

class Sender:
    def __init__(self, env, total_packets, timeout, prep_delay, forward_subnet):
        self.env = env
        self.total_packets = total_packets
        self.timeout = timeout
        self.prep_delay = prep_delay
        self.forward_subnet = forward_subnet
        # Control store to receive ACKs and internal timeout events
        self.control_store = simpy.Store()
        self.env.process(self.run())

    def _timer_process(self):
        """
        Process that waits for timeout duration and signals the control store.
        """
        try:
            yield self.env.timeout(self.timeout)
            yield self.control_store.put({"type": "timeout"})
        except simpy.Interrupt:
            # Timer was interrupted (cancelled), stop gracefully
            pass

    def run(self):
        seq_num = 1
        bit = 0
        count = 0
        
        while count < self.total_packets:
            # Preparation Phase
            SimulationLogger.log(self.env.now, "sender", "delay_start", {
                "type": "preparation",
                "duration": float(self.prep_delay)
            })
            yield self.env.timeout(self.prep_delay)
            
            is_retry = False
            # Start the timer for this packet
            timer_proc = self.env.process(self._timer_process())
            
            while True:
                # Construct packet
                packet = {"seq_num": seq_num, "bit": bit}
                
                # Log and send packet
                SimulationLogger.log(self.env.now, "sender", "packet_sent", {
                    "seq_num": seq_num,
                    "bit": bit,
                    "is_retry": is_retry
                })
                self.forward_subnet.put(packet)
                
                is_retry = True
                
                # Wait for either an ACK or a Timeout
                msg = yield self.control_store.get()
                
                if msg["type"] == "timeout":
                    # Timer expired, retransmit
                    # Restart timer
                    timer_proc.interrupt()
                    timer_proc = self.env.process(self._timer_process())
                    continue
                
                elif msg["type"] == "ack":
                    ack_bit = msg["bit"]
                    is_valid = (ack_bit == bit)
                    
                    SimulationLogger.log(self.env.now, "sender", "ack_received", {
                        "ack_bit": ack_bit,
                        "is_valid": is_valid
                    })
                    
                    if is_valid:
                        # Valid ACK received
                        timer_proc.interrupt() # Stop timer
                        seq_num += 1
                        bit = 1 - bit
                        count += 1
                        break # Move to next packet
                    else:
                        # Invalid ACK, ignore it and continue waiting
                        # (Timer is still running unless it fired concurrently, 
                        # but since we yielded on control_store, if timer fired 
                        # we would be in the other branch. So timer is still pending.)
                        continue

def main():
    parser = argparse.ArgumentParser(description="Reliable Data Transfer Simulation with ABP")
    parser.add_argument("--total_packets", type=int, required=True, help="Total packets to send")
    parser.add_argument("--seed", type=int, default=42, help="Initialization seed for noise generator")
    parser.add_argument("--timeout", type=int, default=20, help="Sender timeout duration in ms")
    parser.add_argument("--sender_delay", type=int, default=10, help="Sender preparation delay in ms")
    parser.add_argument("--receiver_delay", type=int, default=10, help="Receiver processing delay in ms")
    parser.add_argument("--channel_delay", type=int, default=3, help="Subnet transmission delay in ms")
    parser.add_argument("--simulate_time", type=int, default=1000, help="Total simulation time in ms")
    
    args = parser.parse_args()
    
    # Initialize SimPy Environment
    env = simpy.Environment()
    
    # Create communication stores
    # Receiver inbox (capacity 1)
    receiver_inbox = simpy.Store(capacity=1)
    # Sender control store (for ACKs and timeouts)
    sender_control = simpy.Store()
    
    # Create Subnets
    # Forward channel: Sender -> Receiver
    subnet_forward = Subnet(env, "forward", args.channel_delay, args.seed, receiver_inbox)
    # Backward channel: Receiver -> Sender
    subnet_backward = Subnet(env, "backward", args.channel_delay, args.seed, sender_control)
    
    # Create Entities
    receiver = Receiver(env, args.receiver_delay, subnet_backward)
    sender = Sender(env, args.total_packets, args.timeout, args.sender_delay, subnet_forward)
    
    # Run simulation
    env.run(until=args.simulate_time)

if __name__ == "__main__":
    main()