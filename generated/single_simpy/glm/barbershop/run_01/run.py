import sys
import argparse
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

def parse_time(time_str):
    """
    Parses HH:MM:SS:mm into seconds (float).
    """
    parts = time_str.strip().split(':')
    if len(parts) != 4:
        logger.error(f"Invalid time format: {time_str}")
        return 0.0
    
    h, m, s = map(int, parts[:3])
    ms = int(parts[3])
    return h * 3600 + m * 60 + s + ms / 1000.0

def log_state(time, model, field, value):
    """
    Logs a state change event to stdout as JSONL.
    """
    record = {
        "time": round(time, 2),
        "type": "state",
        "model": model,
        "field": field,
        "value": value
    }
    print(json.dumps(record))
    sys.stdout.flush()

def log_message(time, model, port, content):
    """
    Logs a communication event to stdout as JSONL.
    """
    record = {
        "time": round(time, 2),
        "type": "message",
        "model": model,
        "port": port,
        "content": content
    }
    print(json.dumps(record))
    sys.stdout.flush()

def reception_process(env, waiting_queue, checkhair_resource, checkhair_in, reception_feedback):
    """
    Simulates the Reception Desk logic.
    """
    is_busy = False
    
    while True:
        # Wait for a customer to be in the waiting queue
        # We check the queue size manually to log state changes correctly
        if len(waiting_queue.items) > 0:
            # Customer moves from waiting to processing
            # Total count remains the same, so no state log here for 'total customers num'
            # However, we need to actually get the item from the store to process it
            cust = yield waiting_queue.get()
            is_busy = True
            
            # Processing: Hold for 5 seconds
            yield env.timeout(5)
            
            # Handoff: Wait until checkhair is available
            with checkhair_resource.request() as req:
                yield req
                
                # Send customer to Checkhair
                log_message(env.now, "reception", "cust", "newcust")
                yield checkhair_in.put("newcust")
                
                # Wait for feedback from Checkhair (service complete)
                yield reception_feedback.get()
            
            # Customer has left reception
            is_busy = False
            # Update state: total customers decreased
            current_total = len(waiting_queue.items) # is_busy is False now
            log_state(env.now, "reception", "total customers num", current_total)
        else:
            # If queue is empty, wait a tiny bit to prevent busy loop
            # In a real SimPy model, we'd usually yield on the queue get directly,
            # but we need to interleave logic for state logging.
            # A better approach for SimPy is to just yield the get, but we need to handle
            # the state logic *around* it.
            
            # Let's refactor the loop to be more SimPy-idiomatic:
            # Just wait for the next item.
            cust = yield waiting_queue.get()
            is_busy = True
            
            # Log state? The customer moved from queue to processing. Total is same.
            # But we might want to log if we tracked 'waiting' vs 'processing'.
            # The requirement only asks for "total customers num".
            
            yield env.timeout(5)
            
            with checkhair_resource.request() as req:
                yield req
                
                log_message(env.now, "reception", "cust", "newcust")
                yield checkhair_in.put("newcust")
                
                yield reception_feedback.get()
            
            is_busy = False
            current_total = len(waiting_queue.items)
            log_state(env.now, "reception", "total customers num", current_total)

def checkhair_process(env, checkhair_in, cuthair_in, cuthair_out, reception_feedback):
    """
    Simulates the Hair Inspection Phase.
    """
    while True:
        # Receive customer from Reception
        yield checkhair_in.get()
        
        # State: Processing start
        log_state(env.now, "checkhair", "customer", "newcust")
        
        # Process: 7 seconds consultation
        yield env.timeout(7)
        
        # Forward to Cutting
        log_message(env.now, "checkhair", "to_cut", "newcust")
        yield cuthair_in.put("newcust")
        
        # Wait for done signal from Cutting
        yield cuthair_out.get()
        
        # Send notification back to Reception
        log_message(env.now, "checkhair", "to_reception", "done")
        yield reception_feedback.put("done")
        
        # State: Processing complete
        log_state(env.now, "checkhair", "customer", "done")
        # Module becomes available again automatically as the loop restarts

def cuthair_process(env, cuthair_in, cuthair_out):
    """
    Simulates the Hair Cutting Phase.
    """
    total_done = 0
    while True:
        # Receive customer from Inspection
        yield cuthair_in.get()
        
        # Process: 20 seconds cutting
        yield env.timeout(20)
        
        # Completion
        total_done += 1
        log_state(env.now, "cuthair", "total customer done", total_done)
        
        log_message(env.now, "cuthair", "out", "done")
        yield cuthair_out.put("done")

def customer_arrival(env, arrival_time, waiting_queue, checkhair_busy):
    """
    Handles a single customer arrival event at a specific time.
    """
    yield env.timeout(arrival_time - env.now)
    
    # Check Queue Size
    # Queue capacity is 8.
    # Logic: "If Queue < 8: Accept customer".
    # We assume "Queue" refers to the waiting area (waiting_queue).
    # The reception processing (checkhair_busy) is separate.
    
    current_queue_len = len(waiting_queue.items)
    
    if current_queue_len < 8:
        # Accept customer
        yield waiting_queue.put("customer")
        
        # Update State: total customers num
        # Total = waiting_queue + (1 if checkhair_busy else 0)
        # Note: checkhair_busy here refers to the reception desk being busy with check-in?
        # No, the prompt says "Reception processes customers independently of the Barber."
        # But "Reception: Processing: 1 customer at a time".
        # So we need to know if Reception is currently processing the 5s check-in.
        # We can infer this by checking if the reception process is holding a customer 
        # but that's hard to see from outside.
        # However, the state "total customers num" is defined as "The current total number of customers in the reception desk."
        # This implies Waiting + Being Processed by Reception.
        
        # We can calculate this by checking the waiting_queue length.
        # But the customer was just added.
        # If reception is processing, that customer is NOT in waiting_queue.
        # So we need a way to know if reception is busy.
        # Let's pass a shared object or just calculate based on the fact that 
        # if we just added one, the total is len(queue) + 1 (if reception busy) or len(queue) (if not).
        # Actually, simpler: The `reception_process` manages the state when it takes a customer.
        # When a customer arrives, we add to queue. The count increases by 1.
        # We just need to log the new total.
        
        # Wait, if reception is busy, the customer in processing is NOT in the queue.
        # So Total = len(queue) + 1.
        # If reception is idle, Total = len(queue).
        # How do we know if reception is busy?
        # We can use a simpy.Resource for the reception desk itself? 
        # Or a shared list/variable.
        # Let's use a shared list `reception_state` = ['busy'] or [].
        
        # Actually, looking at the `reception_process`, it takes an item from the queue immediately if available.
        # So `waiting_queue` will almost always be empty if reception is fast enough?
        # No, reception takes 5s. Arrivals can be faster.
        # So `waiting_queue` holds the backlog.
        # The reception process holds 1 customer.
        # So Total = len(waiting_queue.items) + 1 (because we just put one in, 
        # and reception might have taken one out already or is processing one).
        
        # Let's refine: `reception_process` does `cust = yield waiting_queue.get()`.
        # This removes it from the queue.
        # So at any moment, `waiting_queue` has only those WAITING.
        # The one being processed is NOT in the queue.
        # So Total = len(waiting_queue.items) + (1 if reception_processing else 0).
        
        # We need `reception_processing` flag.
        pass 
    else:
        # Ignore customer
        pass

    # Revised Arrival Logic with Shared State
    # We need to know the total count to log it.
    # We can't easily access the 'is_busy' variable of the generator.
    # We will use a shared dictionary or a simple class to hold state.
    
def main():
    parser = argparse.ArgumentParser(description="Barbershop Simulation")
    parser.add_argument("--simulation_time", type=float, default=1000000.0, help="Total simulation time in seconds")
    args = parser.parse_args()

    # Read all input from stdin first
    input_lines = sys.stdin.readlines()
    events = []
    for line in input_lines:
        line = line.strip()
        if not line:
            continue
        try:
            parts = line.split()
            if len(parts) != 2:
                logger.warning(f"Skipping malformed line: {line}")
                continue
            time_str, event_name = parts
            if event_name != "newcust":
                logger.warning(f"Skipping unknown event: {event_name}")
                continue
            
            sim_time = parse_time(time_str)
            events.append((sim_time, event_name))
        except Exception as e:
            logger.error(f"Error parsing line {line}: {e}")

    # Sort events by time
    events.sort(key=lambda x: x[0])

    # Setup SimPy Environment
    env = simpy.Environment()

    # Shared State for Reception
    # We use a container to track if reception is busy processing a customer
    reception_busy_flag = {"value": False}

    # Communication Channels (Stores)
    # Capacity 1 usually acts as a buffer/handshake
    waiting_queue = simpy.Store(env, capacity=8) # Waiting area
    checkhair_in = simpy.Store(env) # Reception -> Checkhair
    cuthair_in = simpy.Store(env)   # Checkhair -> Cuthair
    cuthair_out = simpy.Store(env)  # Cuthair -> Checkhair
    reception_feedback = simpy.Store(env) # Checkhair -> Reception

    # Resources
    # Checkhair availability (1 at a time)
    checkhair_resource = simpy.Resource(env, capacity=1)

    # Start Processes
    env.process(reception_process(env, waiting_queue, checkhair_resource, checkhair_in, reception_feedback))
    env.process(checkhair_process(env, checkhair_in, cuthair_in, cuthair_out, reception_feedback))
    env.process(cuthair_process(env, cuthair_in, cuthair_out))

    # Schedule Arrivals
    # We need a wrapper to handle the state logging for arrivals
    def arrival_wrapper(time, _):
        yield env.timeout(time - env.now)
        
        # Calculate current total
        # Total = len(waiting_queue) + (1 if reception_busy else 0)
        # Note: waiting_queue.items contains items NOT yet picked up by reception_process
        # reception_process picks one up immediately if it's idle.
        
        # However, there is a race condition or ordering issue in discrete event simulation.
        # If we `put` here, and `reception_process` is waiting on `get`, 
        # the `get` happens immediately in the same time step.
        # We need to ensure the logging happens correctly.
        
        # Let's look at the logic:
        # 1. Check capacity (Queue < 8).
        # 2. If yes, Accept. Increment count.
        # 3. Reception picks up (if idle). Count stays same.
        
        # If we use a simple Store, `put` succeeds if not full.
        # We check capacity manually.
        
        current_waiting = len(waiting_queue.items)
        # If reception is busy, the customer being processed is NOT in waiting_queue.
        # So total = current_waiting + (1 if reception_busy_flag["value"] else 0)
        
        # The requirement says: "Queue: The waiting area has a strict capacity of 8."
        # "If Queue < 8: Accept customer".
        # This implies we check `current_waiting < 8`.
        
        if current_waiting < 8:
            # Accept
            # We put the customer. 
            # Note: If reception is idle, it will pick this up instantly.
            # If reception is busy, it sits in the queue.
            
            # To log the state correctly, we need to know the state *after* the event.
            # If reception is idle, it picks it up. Total = 1 (processing) + 0 (waiting) = 1.
            # If reception is busy, it waits. Total = 1 (processing) + 1 (waiting) = 2.
            
            # We need to coordinate this. 
            # We can't just `put` and then log, because `reception_process` might run in between.
            # SimPy processes run until they yield.
            
            # Strategy:
            # The `reception_process` is the one that should log the state change when it picks up a customer?
            # No, the requirement says "Arrival: ... Accept customer, increment queue count."
            # This implies the arrival event triggers the log.
            
            # Let's assume "Queue" in the requirement "If Queue < 8" refers to the `waiting_queue`.
            # So we check `len(waiting_queue.items)`.
            
            # We will put the customer.
            # Then we calculate the total.
            # Total = len(waiting_queue.items) + (1 if reception_busy_flag["value"] else 0)
            # BUT, if reception was idle, it took the item. `len` is 0. `busy` is now True.
            # If reception was busy, it didn't take. `len` is 1. `busy` is True.
            
            # We need a way to atomically "Add and Log".
            # Since SimPy is single-threaded, we can do:
            
            was_busy = reception_busy_flag["value"]
            
            # We need to put the item.
            # If we do `yield waiting_queue.put(...)`, control passes to other processes.
            # `reception_process` might run and set `reception_busy_flag["value"] = True`.
            # So when we come back, `reception_busy_flag["value"]` is definitely True.
            # And `len(waiting_queue.items)` depends on whether it was picked up.
            
            yield waiting_queue.put("customer")
            
            # After put:
            # If was_busy is True: Reception didn't pick it up (busy).
            #    Total = len(waiting_queue.items) + 1.
            # If was_busy is False: Reception picked it up immediately.
            #    Total = len(waiting_queue.items) + 1 (because it's now processing).
            
            # Wait, if reception picked it up, `len(waiting_queue.items)` is 0 (assuming it was empty).
            # And `reception_busy_flag` is True.
            # So Total = 0 + 1 = 1. Correct.
            
            # If reception was busy, `len` is 1. `reception_busy_flag` is True.
            # Total = 1 + 1 = 2. Correct.
            
            # So the formula is always: len(waiting_queue.items) + 1
            # Because the customer we just added is either in the queue or in processing.
            # And `reception_busy_flag` is True in both cases (if it was False, it became True).
            
            # Wait, what if reception was idle?
            # 1. `was_busy` = False.
            # 2. `put` triggers `reception_process`.
            # 3. `reception_process` gets item, sets `busy` = True.
            # 4. Control returns here.
            # 5. `len(waiting_queue.items)` is 0.
            # 6. Total = 0 + 1 = 1. Correct.
            
            # What if reception was busy?
            # 1. `was_busy` = True.
            # 2. `put` adds to queue. `reception_process` is blocked (busy).
            # 3. Control returns.
            # 4. `len(waiting_queue.items)` is 1.
            # 5. Total = 1 + 1 = 2. Correct.
            
            # So the formula `len(waiting_queue.items) + 1` works for the new total.
            
            new_total = len(waiting_queue.items) + 1
            log_state(env.now, "reception", "total customers num", new_total)
            
        else:
            # Ignore
            pass

    for t, name in events:
        env.process(arrival_wrapper(t, name))

    # Run Simulation
    logger.info(f"Starting simulation for {args.simulation_time} seconds.")
    env.run(until=args.simulation_time)
    logger.info("Simulation finished.")

if __name__ == "__main__":
    main()