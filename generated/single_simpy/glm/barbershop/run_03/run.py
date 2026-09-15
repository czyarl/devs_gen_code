import argparse
import sys
import json
import logging
import collections
import random
import simpy

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

def parse_time(time_str):
    """Parses HH:MM:SS:mm string to simulation seconds."""
    parts = time_str.split(':')
    if len(parts) != 4:
        raise ValueError(f"Invalid time format: {time_str}")
    h, m, s, ms = map(int, parts)
    return h * 3600 + m * 60 + s + ms / 1000.0

def print_json_record(record):
    """Prints a dictionary as a JSON line to stdout."""
    print(json.dumps(record))

class Reception:
    def __init__(self, env, incoming_store, out_to_checkhair):
        self.env = env
        self.incoming = incoming_store
        self.out = out_to_checkhair
        self.queue = collections.deque()
        self.max_capacity = 8
        self.process_time = 5.0
        self.name = "reception"
        self.total_customers_num = 0
        self.is_processing = False
        self.process = env.process(self.run())

    def log_state(self, field, value):
        print_json_record({
            "time": self.env.now,
            "type": "state",
            "model": self.name,
            "field": field,
            "value": value
        })

    def log_message(self, port, content):
        print_json_record({
            "time": self.env.now,
            "type": "message",
            "model": self.name,
            "port": port,
            "content": content
        })

    def try_process_queue(self):
        if not self.is_processing and self.queue:
            self.is_processing = True
            # Schedule the processing of the first customer in queue
            self.env.process(self.process_customer(self.queue[0]))

    def process_customer(self, customer):
        # 2. Processing: Hold the customer for exactly 5 seconds.
        yield self.env.timeout(self.process_time)
        
        # 3. Handoff: Try to send to Checkhair.
        # If Checkhair is busy (store full), this yield blocks until it's available.
        yield self.out.put(customer)
        
        # Log the message sent
        self.log_message("cust", "newcust")
        
        # Remove customer from queue after successfully sending
        self.queue.popleft()
        self.total_customers_num = len(self.queue)
        self.log_state("total customers num", self.total_customers_num)
        
        # Mark processing as done and trigger next
        self.is_processing = False
        self.try_process_queue()

    def run(self):
        while True:
            # 1. Arrival: Wait for input from external source
            event = yield self.incoming.get()
            
            if len(self.queue) < self.max_capacity:
                self.queue.append(event)
                self.total_customers_num = len(self.queue)
                self.log_state("total customers num", self.total_customers_num)
                # Attempt to start processing if idle
                self.try_process_queue()
            else:
                # Queue = 8: Ignore new customer
                pass

class HairInspection:
    def __init__(self, env, in_from_reception, out_to_cuthair, in_from_cuthair, out_to_reception):
        self.env = env
        self.in_reception = in_from_reception
        self.out_cut = out_to_cuthair
        self.in_cut = in_from_cuthair
        self.out_reception = out_to_reception
        self.process_time = 7.0
        self.name = "checkhair"
        self.customer_status = None
        
        self.process = env.process(self.run())

    def log_state(self, field, value):
        print_json_record({
            "time": self.env.now,
            "type": "state",
            "model": self.name,
            "field": field,
            "value": value
        })

    def log_message(self, port, content):
        print_json_record({
            "time": self.env.now,
            "type": "message",
            "model": self.name,
            "port": port,
            "content": content
        })

    def run(self):
        while True:
            # 1. Receive: Accept customer from Reception Desk
            customer = yield self.in_reception.get()
            
            # State change: Processing start
            self.customer_status = "newcust"
            self.log_state("customer", self.customer_status)
            
            # 2. Process: Hold customer for exactly 7 seconds
            yield self.env.timeout(self.process_time)
            
            # 3. Forward: Send customer to Hair Cutting Phase
            yield self.out_cut.put(customer)
            self.log_message("to_cut", "newcust")
            
            # 4. Coordination: Wait for "done" signal from Hair Cutting Phase
            yield self.in_cut.get()
            
            # 5. Completion: State change
            self.customer_status = "done"
            self.log_state("customer", self.customer_status)
            
            # Send notification back to Reception
            yield self.out_reception.put("done")
            self.log_message("to_reception", "done")
            
            # Loop back to available state

class HairCutting:
    def __init__(self, env, in_from_checkhair, out_to_checkhair):
        self.env = env
        self.in_check = in_from_checkhair
        self.out_check = out_to_checkhair
        self.process_time = 20.0
        self.name = "cuthair"
        self.total_customer_done = 0
        
        self.process = env.process(self.run())

    def log_state(self, field, value):
        print_json_record({
            "time": self.env.now,
            "type": "state",
            "model": self.name,
            "field": field,
            "value": value
        })

    def log_message(self, port, content):
        print_json_record({
            "time": self.env.now,
            "type": "message",
            "model": self.name,
            "port": port,
            "content": content
        })

    def run(self):
        while True:
            # 1. Receive: Accept customer from Hair Inspection Phase
            customer = yield self.in_check.get()
            
            # 2. Process: Hold customer for exactly 20 seconds
            yield self.env.timeout(self.process_time)
            
            # 3. Completion: Signal back to Hair Inspection Phase
            yield self.out_check.put("done")
            self.log_message("out", "done")
            
            # Update stats
            self.total_customer_done += 1
            self.log_state("total customer done", self.total_customer_done)

def main():
    parser = argparse.ArgumentParser(description="Barbershop Simulation")
    parser.add_argument("--simulation_time", type=float, default=1000000.0, help="Total simulation time in seconds")
    args = parser.parse_args()

    # 1. Read Input Data from Stdin
    input_events = []
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 2:
                logger.warning(f"Skipping malformed line: {line}")
                continue
            
            time_str, event_name = parts
            if event_name != "newcust":
                logger.warning(f"Unknown event type: {event_name}")
                continue
            
            try:
                sim_time = parse_time(time_str)
                input_events.append((sim_time, event_name))
            except ValueError as e:
                logger.warning(f"Skipping line with invalid time: {line} ({e})")
        
        # Sort events by time
        input_events.sort(key=lambda x: x[0])
        logger.info(f"Read {len(input_events)} events from stdin.")

    except Exception as e:
        logger.error(f"Error reading stdin: {e}")
        sys.exit(1)

    # 2. Setup Environment
    env = simpy.Environment()
    
    # 3. Initialize Communication Channels (Stores)
    # Reception -> Checkhair (Capacity 1 to enforce availability check)
    reception_to_checkhair = simpy.Store(env, capacity=1)
    # Checkhair -> Cuthair
    checkhair_to_cuthair = simpy.Store(env, capacity=1)
    # Cuthair -> Checkhair
    cuthair_to_checkhair = simpy.Store(env, capacity=1)
    # Checkhair -> Reception (Notification)
    checkhair_to_reception = simpy.Store(env, capacity=1000)
    
    # External -> Reception
    external_to_reception = simpy.Store(env)

    # 4. Instantiate Modules
    reception = Reception(env, external_to_reception, reception_to_checkhair)
    checkhair = HairInspection(env, reception_to_checkhair, checkhair_to_cuthair, cuthair_to_checkhair, checkhair_to_reception)
    cuthair = HairCutting(env, checkhair_to_cuthair, cuthair_to_checkhair)

    # Drain notifications from Checkhair to Reception to prevent blocking
    # (Reception logic does not explicitly wait for these, but Checkhair sends them)
    def notification_drain():
        while True:
            yield checkhair_to_reception.get()
    env.process(notification_drain())

    # 5. Start Input Feeder
    def input_feeder():
        for t, event in input_events:
            # Wait until the specific simulation time
            yield env.timeout(t - env.now)
            # Inject event into Reception
            yield external_to_reception.put(event)
    
    env.process(input_feeder())

    # 6. Run Simulation
    logger.info(f"Starting simulation for {args.simulation_time} seconds.")
    env.run(until=args.simulation_time)
    logger.info("Simulation finished.")

if __name__ == "__main__":
    main()