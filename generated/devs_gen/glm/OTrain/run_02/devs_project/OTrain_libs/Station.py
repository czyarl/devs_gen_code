import json
import random
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time

# Constants for Passenger Generation (R006)
# Mean: 5.0 min, Std: 5.0 min -> Clamped [1, 9] min -> Seconds
GEN_MEAN_MIN = 5.0
GEN_STD_MIN = 5.0
GEN_MIN_MIN = 1.0
GEN_MAX_MIN = 9.0

# Constants for Boarding (R007)
BOARDING_DELAY = 0.025

# Constants for Initialization (R006)
INIT_TIME = 0.5


class Station(Atomic):
    """
    Atomic DEVS model for a Station.
    Manages passenger generation and boarding.
    """

    def __init__(self, name: str, parent: Coupled | None, station_id: int, station_name: str):
        super().__init__(name)
        self.parent = parent
        
        # Locked Interface: Constructor arguments
        self.station_id = station_id
        self.station_name = station_name

        # Locked Interface: Ports
        self.add_in_port(Port(dict, "train_arrival_in"))
        self.add_out_port(Port(dict, "boarding_out"))

        # Internal State
        self.queue = []  # FIFO queue of waiting passengers (dicts)
        self.passenger_num = 0  # Counter for generated passengers (excluding init)
        self.next_gen_time = 0.0  # Absolute time for next generation event
        
        # State for Boarding Logic
        self.boarding_passenger = None # The passenger currently being boarded/outputted

    def _generate_passenger(self, is_init: bool = False) -> dict:
        """Helper to create a passenger dictionary."""
        if is_init:
            pid = 0
            p_num = 0
            origin = self.station_id
            # Random destination different from origin
            possible_dests = [sid for sid in range(1, 6) if sid != origin]
            destination = random.choice(possible_dests)
        else:
            self.passenger_num += 1
            p_num = self.passenger_num
            origin = self.station_id
            possible_dests = [sid for sid in range(1, 6) if sid != origin]
            destination = random.choice(possible_dests)
            pid = p_num * 100 + origin * 10 + destination

        return {
            "passenger_id": pid,
            "passenger_num": p_num,
            "origin": origin,
            "destination": destination
        }

    def _write_jsonl(self, record: dict):
        """Helper to write JSONL to stdout."""
        print(json.dumps(record), flush=True)

    def _schedule_generation(self, current_time: float):
        """Calculate and schedule the next generation interval."""
        # Normal distribution in minutes
        mean = GEN_MEAN_MIN
        std = GEN_STD_MIN
        interval_min = random.gauss(mean, std)
        
        # Clamp to [1, 9] minutes
        interval_min = max(GEN_MIN_MIN, min(GEN_MAX_MIN, interval_min))
        
        # Convert to seconds and round to nearest integer
        interval_sec = round(interval_min * 60)
        
        self.next_gen_time = current_time + interval_sec

    def initialize(self):
        # 1. Initialization & Generation (R006)
        # At t=0.5s, generate init passenger.
        self.passenger_num = 0
        self.queue = []
        self.boarding_passenger = None
        
        # Schedule the initialization event
        self.hold_in("INIT", INIT_TIME)

    def deltext(self, e: float):
        # Handle Train Arrival
        # Protocol: Receive train arrival broadcast. Process only if station_id matches own ID.
        
        # Check inputs
        for msg in self.input["train_arrival_in"].values:
            if msg.get("station_id") == self.station_id:
                # Valid train arrival for this station.
                # If we are not already boarding, and queue is not empty, start boarding.
                if self.phase != "BOARDING" and self.phase != "BOARDING_OUTPUT" and self.queue:
                    # Start boarding sequence
                    # The first passenger boards 0.025s after arrival.
                    self.hold_in("BOARDING", BOARDING_DELAY)
                elif self.phase == "IDLE":
                    # Train arrived but queue empty. 
                    # We must preserve the time to next generation.
                    self.continuef(e)
                elif self.phase == "BOARDING" or self.phase == "BOARDING_OUTPUT":
                    # Already boarding, ignore new train.
                    pass
                # If in INIT or GENERATE, we ignore train arrivals as per strict phase priority 
                # (or we could interrupt, but generation is instantaneous/internal logic).
                # Given atomic nature, we finish current internal transition.
            else:
                # Train for other station, ignore.
                if self.phase == "IDLE":
                    self.continuef(e)

        # If we are in IDLE and no valid train arrived to trigger boarding, continue waiting.
        if self.phase == "IDLE":
             # We need to ensure we don't reset sigma if we were just continuing.
             # continuef(e) handles the subtraction.
             # However, if we didn't call continuef inside the loop (e.g. no inputs or ignored inputs),
             # we must still subtract elapsed time if we are in a phase that allows it.
             # But xDEVS Atomic semantics: if we don't call hold_in or passivate, the phase remains but sigma might need update?
             # Actually, `continuef` is the explicit way to say "stay in phase, reduce sigma".
             # If we are in IDLE, we are waiting for an internal event (generation).
             # External events (train arrivals) do not consume the IDLE time unless they trigger a state change.
             # So if we are in IDLE and receive an ignored train arrival, we must `continuef(e)`.
             # The logic above covers `if self.phase == "IDLE": self.continuef(e)` for the ignored case.
             pass

    def lambdaf(self):
        # 2. Boarding Output
        if self.phase == "BOARDING_OUTPUT":
            # "sends the passenger data dictionary via the `boarding_out` port."
            if self.boarding_passenger:
                self.output["boarding_out"].add(self.boarding_passenger)
                
                # External IO: passenger_boarding
                record = {
                    "time": get_current_time(),
                    "event": "passenger_boarding",
                    "entity_type": "station_queue",
                    "station_id": self.station_id,
                    "station": self.station_name,
                    "payload": self.boarding_passenger
                }
                self._write_jsonl(record)

    def deltint(self):
        current_time = get_current_time()

        if self.phase == "INIT":
            # Generate initialization passenger
            p = self._generate_passenger(is_init=True)
            self.queue.append(p)
            
            # External IO: passenger_generated
            record = {
                "time": current_time,
                "event": "passenger_generated",
                "entity_type": "passenger_generator",
                "station_id": self.station_id,
                "station": self.station_name,
                "payload": p
            }
            self._write_jsonl(record)
            
            # Schedule first stochastic generation
            self._schedule_generation(current_time)
            
            # Transition to IDLE, waiting for next event
            sigma = self.next_gen_time - current_time
            self.hold_in("IDLE", sigma)

        elif self.phase == "GENERATE":
            # Generate regular passenger
            p = self._generate_passenger(is_init=False)
            self.queue.append(p)
            
            # External IO: passenger_generated
            record = {
                "time": current_time,
                "event": "passenger_generated",
                "entity_type": "passenger_generator",
                "station_id": self.station_id,
                "station": self.station_name,
                "payload": p
            }
            self._write_jsonl(record)
            
            # Schedule next generation
            self._schedule_generation(current_time)
            
            # Transition to IDLE
            sigma = self.next_gen_time - current_time
            self.hold_in("IDLE", sigma)

        elif self.phase == "BOARDING":
            # Internal timeout for boarding delay finished.
            # We are ready to output the boarded passenger.
            # Pop from queue
            if self.queue:
                self.boarding_passenger = self.queue.pop(0)
                # Transition to output phase (sigma=0)
                self.hold_in("BOARDING_OUTPUT", 0.0)
            else:
                # Queue empty? Should not happen if we entered BOARDING correctly.
                # But safe fallback.
                self.passivate("IDLE")

        elif self.phase == "BOARDING_OUTPUT":
            # Output done (lambdaf executed).
            # Check if more passengers to board
            self.boarding_passenger = None
            if self.queue:
                # Schedule next boarding
                self.hold_in("BOARDING", BOARDING_DELAY)
            else:
                # Boarding finished.
                # Go back to IDLE.
                # Need to check if we missed a generation event while boarding.
                # If next_gen_time <= current_time, we need to generate immediately.
                # Otherwise wait.
                if self.next_gen_time <= current_time:
                    self.hold_in("GENERATE", 0.0)
                else:
                    sigma = self.next_gen_time - current_time
                    self.hold_in("IDLE", sigma)

        elif self.phase == "IDLE":
            # This case handles if we wake up from IDLE without external input.
            # This means the generation timer expired.
            # Switch to GENERATE phase to produce the passenger.
            self.hold_in("GENERATE", 0.0)
            
        else:
            self.passivate("IDLE")

    def exit(self):
        pass