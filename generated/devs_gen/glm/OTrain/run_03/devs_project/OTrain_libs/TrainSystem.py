import sys
import json
import time
import random
import heapq
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time

# Constants
STATIONS = {
    1: "Bayview",
    2: "Carling",
    3: "Carleton",
    4: "Confed",
    5: "Greenboro"
}

TRAVEL_TIME = 225.0  # seconds
BOARDING_DELAY = 0.025  # seconds
ALIGHTING_DELAY = 0.025  # seconds
SIMULATION_HORIZON = 60.0 * 60.0  # Default 1 hour in seconds, will be overridden by runner if needed, but atomic model runs until horizon

# Route definition
# (Station ID, Direction)
# Direction 0: Southbound (Bayview -> Greenboro)
# Direction 1: Northbound (Greenboro -> Bayview)
ROUTE_SEQUENCE = [
    (1, 0), (2, 0), (3, 0), (4, 0), (5, 1),
    (4, 1), (3, 1), (2, 1), (1, 0)
]

class TrainSystem(Atomic):
    """
    Orchestrates the entire O-Train simulation logic internally.
    Maintains state for train, passengers, and queues.
    Outputs JSONL records to stdout.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # No input or output ports defined in the locked contract
        # self.add_in_port(...)
        # self.add_out_port(...)

        # Internal State
        self.time_horizon = 3600.0  # Default 1 hour, usually set by runner via environment or just run until end
        # Note: The prompt mentions "The generated runner owns CLI parsing", but we are the atomic model.
        # The locked contract doesn't pass time_horizon in __init__.
        # However, the contract says "The simulation runs until the specified time horizon is reached."
        # We will assume the runner handles the termination or we need to detect it.
        # Since we are an atomic model in a simulation, we usually passivate when done.
        # But we are the "entire simulation logic".
        # We will check if the next event time > horizon in deltint.

        # Train State
        self.train_station_id = 1
        self.train_direction = 0
        self.train_next_arrival_time = 0.0
        
        # Queues
        # station_queues[station_id] = list of passengers (dicts)
        self.station_queues = {i: [] for i in range(1, 6)}
        
        # Train Passengers
        # train_passengers[destination_id] = list of passengers (dicts)
        self.train_passengers = {i: [] for i in range(1, 6)}

        # Passenger Generation State
        self.passenger_counters = {i: 0 for i in range(1, 6)} # passenger_num per station
        self.next_generation_times = {i: 0.5 for i in range(1, 6)} # Initial at 0.5

        # Event Queue (Priority Queue)
        # Items: (time, type, count, data)
        # Types: "GENERATE", "ARRIVE", "BOARD", "ALIGHT"
        self.event_queue = []
        self._event_counter = 0

        # Pending Output for lambdaf
        self.pending_output = None

        # Random Seed setup (R009)
        # Use system time to set the seed
        seed_val = time.time_ns()
        random.seed(seed_val)
        # numpy is allowed but not strictly required if we use random module for normal dist
        # However, R009 mentions numpy. We'll stick to standard random if possible, or numpy if needed.
        # Standard random.gauss is available.
        # random.seed(time.time_ns())

    def _schedule_event(self, time: float, event_type: str, data: dict):
        self._event_counter += 1
        heapq.heappush(self.event_queue, (time, event_type, self._event_counter, data))

    def _get_next_station(self, current_id: int, current_dir: int) -> tuple[int, int]:
        # Find current index in ROUTE_SEQUENCE
        try:
            idx = ROUTE_SEQUENCE.index((current_id, current_dir))
        except ValueError:
            # Should not happen if logic is correct
            return (1, 0)
        
        next_idx = (idx + 1) % len(ROUTE_SEQUENCE)
        return ROUTE_SEQUENCE[next_idx]

    def _generate_passenger(self, station_id: int, t: float):
        # Determine destination
        possible_destinations = [s for s in range(1, 6) if s != station_id]
        destination = random.choice(possible_destinations)
        
        # Determine ID
        # passenger_id = passenger_num * 100 + origin * 10 + destination
        # Exception: Initial passenger at t=0.5 has ID 0.
        # We need to track passenger_num.
        
        is_initial = (t == 0.5)
        
        if is_initial:
            p_id = 0
            p_num = 0
        else:
            self.passenger_counters[station_id] += 1
            p_num = self.passenger_counters[station_id]
            p_id = p_num * 100 + station_id * 10 + destination

        passenger = {
            "passenger_id": p_id,
            "passenger_num": p_num,
            "origin": station_id,
            "destination": destination
        }

        # Add to station queue
        self.station_queues[station_id].append(passenger)

        # Create Output Record
        record = {
            "time": t,
            "event": "passenger_generated",
            "entity_type": "passenger_generator",
            "station_id": station_id,
            "station": STATIONS[station_id],
            "payload": passenger
        }
        
        # Write immediately? No, xDEVS models usually output via ports or lambdaf.
        # But the contract says "external_io": "Write JSONL records... to stdout".
        # And "external_io" is a side effect.
        # The Atomic Core Rules say: "Perform normal Python IO at the required semantic point inside initialize, deltext, lambdaf, deltint, exit, or a helper".
        # Since this is an internal event processing (simulating discrete event logic inside an Atomic model),
        # we can write directly to stdout here or buffer it.
        # However, to keep with the "autonomous_timed_worker" pattern and strict xDEVS separation,
        # we should probably buffer the output and emit it in lambdaf?
        # Wait, the contract says "Orchestrates the entire O-Train simulation logic internally".
        # It acts as a "self-contained discrete-event engine".
        # It doesn't use DEVS ports for communication. It writes to stdout.
        # So `lambdaf` might be empty if we don't use ports.
        # But we must use `lambdaf` if we have output ports. We have no output ports.
        # So we can write to stdout directly in `deltint` or helper.
        # Let's write to stdout directly as the event is processed.
        print(json.dumps(record), flush=True)

        # Schedule next generation for this station
        if not is_initial:
            # Normal Distribution (Mean=5.0 min, Std=5.0 min)
            # Clamp [1, 9] minutes -> seconds -> round to nearest int
            mean = 5.0 * 60.0
            std = 5.0 * 60.0
            interval = random.gauss(mean, std)
            
            # Clamp to minutes [1, 9]
            interval_min = max(1.0, min(9.0, interval / 60.0))
            interval_sec = round(interval_min * 60.0)
            
            next_time = t + interval_sec
            self._schedule_event(next_time, "GENERATE", {"station_id": station_id})

    def _handle_arrival(self, t: float, station_id: int, direction: int):
        # 1. Generate Train Arrival Event
        record = {
            "time": t,
            "event": "train_arrival",
            "entity_type": "train",
            "station_id": station_id,
            "station": STATIONS[station_id],
            "payload": {
                "station": station_id,
                "direction": direction
            }
        }
        print(json.dumps(record), flush=True)

        # 2. Handle Alighting (Serial, 0.025s delay)
        # Passengers destined for this station alight one by one.
        # First passenger alights 0.025s after arrival.
        alighting_passengers = self.train_passengers[station_id]
        if alighting_passengers:
            # Schedule the first alighting event
            # We need to process them serially.
            # We can schedule a chain of events or process them here.
            # Since we have an event queue, let's schedule an "ALIGHT" event.
            # Data: index of passenger in the list? Or just pop from list?
            # We need to ensure order. FIFO.
            # Let's schedule an event for the first one.
            # The event handler will pop one, print, and schedule the next if any.
            
            # To handle serial processing, we can schedule a specific event type "ALIGHT_STEP"
            # with the station_id.
            self._schedule_event(t + ALIGHTING_DELAY, "ALIGHT_STEP", {"station_id": station_id})

        # 3. Handle Boarding (Serial, 0.025s delay)
        # Passengers board one by one.
        # First passenger boards 0.025s after arrival.
        boarding_queue = self.station_queues[station_id]
        if boarding_queue:
            # Schedule first boarding step
            self._schedule_event(t + BOARDING_DELAY, "BOARD_STEP", {"station_id": station_id})

        # 4. Schedule Next Arrival
        # Travel time is 225s
        next_station, next_dir = self._get_next_station(station_id, direction)
        self._schedule_event(t + TRAVEL_TIME, "ARRIVE", {"station_id": next_station, "direction": next_dir})

        # Update Train State
        self.train_station_id = next_station # Train is now technically "en route" to next, but state usually reflects current location.
        # Actually, in discrete event, the state is often "at station" or "traveling".
        # Here we just need to know where we are going next.
        # The prompt says "maintains the state of the train (current station, direction, next arrival time)".
        # So let's update current station to the one we just arrived at?
        # Or the one we are going to?
        # Usually "current station" implies where it is right now.
        # But if we schedule the next arrival, we are leaving.
        # Let's keep `train_station_id` as the station we are currently AT (or just arrived at).
        # But the next arrival event needs the target.
        # Let's refine:
        # State: `train_at_station_id`.
        # When we arrive at X, we are at X.
        # We schedule arrival at Y.
        # So `train_station_id` should be updated to X.
        # Wait, my logic above scheduled next arrival based on X.
        # Let's fix state update.
        self.train_station_id = station_id
        self.train_direction = direction
        self.train_next_arrival_time = t + TRAVEL_TIME

    def _handle_alight_step(self, t: float, station_id: int):
        # Check if there are passengers to alight
        if self.train_passengers[station_id]:
            passenger = self.train_passengers[station_id].pop(0) # FIFO
            
            record = {
                "time": t,
                "event": "passenger_exiting",
                "entity_type": "train_queue",
                "station_id": station_id,
                "station": STATIONS[station_id],
                "payload": passenger
            }
            print(json.dumps(record), flush=True)

            # Schedule next alight step if more passengers
            if self.train_passengers[station_id]:
                self._schedule_event(t + ALIGHTING_DELAY, "ALIGHT_STEP", {"station_id": station_id})

    def _handle_board_step(self, t: float, station_id: int):
        # Check if there are passengers to board
        # Validation: Passengers only join the queue if their encoded origin matches the station...
        # This is handled during generation.
        # Validation: Destination is different. Handled during generation.
        
        if self.station_queues[station_id]:
            passenger = self.station_queues[station_id].pop(0) # FIFO
            
            # Add to train
            dest = passenger["destination"]
            self.train_passengers[dest].append(passenger)
            
            record = {
                "time": t,
                "event": "passenger_boarding",
                "entity_type": "station_queue",
                "station_id": station_id,
                "station": STATIONS[station_id],
                "payload": passenger
            }
            print(json.dumps(record), flush=True)

            # Schedule next board step if more passengers
            if self.station_queues[station_id]:
                self._schedule_event(t + BOARDING_DELAY, "BOARD_STEP", {"station_id": station_id})

    def initialize(self):
        # Initialize Random Seed
        # Done in __init__

        # Initialize Train State
        self.train_station_id = 1
        self.train_direction = 0
        self.train_next_arrival_time = 0.0

        # Schedule Initialization Passengers (R020)
        # At t=0.5 for all stations
        for i in range(1, 6):
            self._schedule_event(0.5, "GENERATE", {"station_id": i})

        # Schedule First Train Arrival (R016)
        # t=0.0 at Bayview
        self._schedule_event(0.0, "ARRIVE", {"station_id": 1, "direction": 0})

        # Determine the very first event time to set sigma
        if self.event_queue:
            first_time, _, _, _ = self.event_queue[0]
            self.hold_in("ACTIVE", first_time)
        else:
            self.passivate("DONE")

    def deltint(self):
        # Get current time
        t = get_current_time()

        # Process all events at time t
        # Since we use a priority queue and we are in deltint (internal transition),
        # we process the event(s) that triggered this transition.
        # In standard DEVS, only one event happens at a time.
        # However, if we have multiple events with same time, we process them.
        
        # Pop events with time == t
        # Note: If we schedule events with 0 delay (e.g. 0.025s steps), they will trigger subsequent transitions.
        
        while self.event_queue and self.event_queue[0][0] <= t + 1e-9: # tolerance for float comparison
            time, type, _, data = heapq.heappop(self.event_queue)
            
            if type == "GENERATE":
                self._generate_passenger(data["station_id"], time)
            elif type == "ARRIVE":
                self._handle_arrival(time, data["station_id"], data["direction"])
            elif type == "ALIGHT_STEP":
                self._handle_alight_step(time, data["station_id"])
            elif type == "BOARD_STEP":
                self._handle_board_step(time, data["station_id"])

        # Schedule next internal event
        if self.event_queue:
            next_time, _, _, _ = self.event_queue[0]
            # Check horizon
            # The contract says "The simulation runs until the specified time horizon is reached."
            # We don't have the horizon passed in. 
            # We assume the runner stops the simulation.
            # However, if we want to be safe, we could check if next_time > horizon.
            # Since we don't have horizon, we just schedule.
            delay = next_time - t
            if delay < 0: delay = 0.0
            self.hold_in("ACTIVE", delay)
        else:
            self.passivate("DONE")

    def deltext(self, e: float):
        # No input ports defined, so this shouldn't be called or do nothing.
        # But we must implement it.
        self.continuef(e)

    def lambdaf(self):
        # No output ports defined.
        # All output is written to stdout in the handlers.
        pass

    def exit(self):
        pass