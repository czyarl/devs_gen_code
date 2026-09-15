import json
import random
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class StoreProcess(Atomic):
    """Atomic model encapsulating the entire store cashier simulation logic."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulation_time: str,
        client_mean: float,
        client_stddev: float,
        employee_1_mean: float,
        employee_1_stddev: float,
        employee_2_mean: float,
        employee_2_stddev: float,
        seed: int | None = None,
    ):
        super().__init__(name)
        self.parent = parent

        # Configuration
        self.simulation_time_str = simulation_time
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.employee_1_mean = employee_1_mean
        self.employee_1_stddev = employee_1_stddev
        self.employee_2_mean = employee_2_mean
        self.employee_2_stddev = employee_2_stddev
        
        # Parse simulation horizon to seconds
        # Format: HH:MM:SS:mmm
        parts = simulation_time.split(":")
        if len(parts) != 4:
            raise ValueError(f"Invalid simulation_time format: {simulation_time}")
        hh, mm, ss, mmm = map(int, parts)
        self.simulation_horizon = hh * 3600 + mm * 60 + ss + mmm / 1000.0

        # Randomness
        self.rng = random.Random(seed)

        # State Variables
        self.next_client_id = 1
        self.queue = deque()  # Stores tuples: (client_id, arrival_time)
        
        # Employee status: True if available, False if busy
        self.employee_1_available = True
        self.employee_2_available = True
        
        # Employee current client tracking
        self.employee_1_client_id = None
        self.employee_1_arrival_time = None
        self.employee_2_client_id = None
        self.employee_2_arrival_time = None

        # Internal Event Timing
        self.next_arrival_time = 0.0  # First client at t=0.0
        self.next_service_end_time_1 = float('inf')
        self.next_service_end_time_2 = float('inf')
        
        # Output preparation
        self.events_to_emit = []

    def initialize(self):
        # Calculate first arrival (already 0.0)
        # self._schedule_next_arrival()
        
        # Employees are initially available
        self.next_service_end_time_1 = float('inf')
        self.next_service_end_time_2 = float('inf')

        # Emit initial availability events at t=0.0
        self.hold_in("INITIAL_EMIT", 0.0)

    def _schedule_next_arrival(self):
        """Calculate the next client arrival time based on distribution."""
        if self.next_arrival_time > self.simulation_horizon:
            self.next_arrival_time = float('inf')
            return

        # Sample interval: Normal(mean, stddev) clipped to [0, mean + 5*stddev]
        interval = self.rng.normalvariate(self.client_mean, self.client_stddev)
        max_interval = self.client_mean + 5 * self.client_stddev
        interval = max(0.0, min(interval, max_interval))
        self.next_arrival_time += interval

    def _schedule_service(self, employee_id: int):
        """Calculate service duration for an employee."""
        mean = self.employee_1_mean if employee_id == 1 else self.employee_2_mean
        stddev = self.employee_1_stddev if employee_id == 1 else self.employee_2_stddev
        
        duration = mean
        if stddev > 0:
            duration = self.rng.normalvariate(mean, stddev)
            min_duration = mean - 3 * stddev
            max_duration = mean + 3 * stddev
            duration = max(min_duration, min(duration, max_duration))
        
        current_time = get_current_time()
        end_time = current_time + duration
        
        if employee_id == 1:
            self.next_service_end_time_1 = end_time
        else:
            self.next_service_end_time_2 = end_time

    def _get_time_str(self, time_val: float) -> str:
        """Convert simulation time (seconds) to HH:MM:SS:mmm string."""
        total_ms = int(time_val * 1000 + 0.5)
        ms = total_ms % 1000
        total_seconds = total_ms // 1000
        sec = total_seconds % 60
        total_minutes = total_seconds // 60
        min = total_minutes % 60
        hour = total_minutes // 60
        return f"{hour:02d}:{min:02d}:{sec:02d}:{ms:03d}"

    def _emit_event(self, event_type: str, entity_type: str, entity: str, payload: dict):
        """Helper to print JSONL event."""
        current_time = get_current_time()
        record = {
            "time": current_time,
            "time_str": self._get_time_str(current_time),
            "event": event_type,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload
        }
        print(json.dumps(record), flush=True)

    def deltext(self, e):
        # No input ports, so just continue if active
        if self.phase != "passive":
            self.continuef(e)

    def lambdaf(self):
        if self.events_to_emit:
            for ev in self.events_to_emit:
                self._emit_event(ev["event"], ev["entity_type"], ev["entity"], ev["payload"])
            self.events_to_emit = []

    def deltint(self):
        current_time = get_current_time()

        if self.phase == "INITIAL_EMIT":
            # Emit initial availability, then process first arrival
            self.events_to_emit = [
                {"event": "employee_available", "entity_type": "employee", "entity": "Employee_1", "payload": {"employee_id": 1}},
                {"event": "employee_available", "entity_type": "employee", "entity": "Employee_2", "payload": {"employee_id": 2}}
            ]
            self.hold_in("EMIT_EVENTS", 0.0)
            return

        if self.phase == "PROCESS_ARRIVAL":
            if self.next_arrival_time <= self.simulation_horizon:
                client_id = self.next_client_id
                arrival_time = self.next_arrival_time
                
                self.events_to_emit = [{
                    "event": "client_generated",
                    "entity_type": "client_generator",
                    "entity": "ClientGenerator",
                    "payload": {"client_id": client_id, "arrival_time": arrival_time}
                }]
                
                self.queue.append((client_id, arrival_time))
                self.next_client_id += 1
                self._schedule_next_arrival()
                self.hold_in("EMIT_EVENTS", 0.0)
            else:
                self._schedule_next_internal_event()

        elif self.phase == "EMIT_EVENTS":
            # After emitting events, check for pairing logic
            # This phase is entered after generation or service completion
            paired = False
            new_events = []

            # Try to pair Employee 1
            if self.employee_1_available and self.queue:
                client_id, arrival_time = self.queue.popleft()
                self.employee_1_client_id = client_id
                self.employee_1_arrival_time = arrival_time
                self.employee_1_available = False
                self._schedule_service(1)
                
                new_events.append({
                    "event": "client_paired",
                    "entity_type": "queue",
                    "entity": "Queue",
                    "payload": {"client_id": client_id, "employee_id": 1, "paired_time": current_time}
                })
                paired = True

            # Try to pair Employee 2
            if self.employee_2_available and self.queue:
                client_id, arrival_time = self.queue.popleft()
                self.employee_2_client_id = client_id
                self.employee_2_arrival_time = arrival_time
                self.employee_2_available = False
                self._schedule_service(2)
                
                new_events.append({
                    "event": "client_paired",
                    "entity_type": "queue",
                    "entity": "Queue",
                    "payload": {"client_id": client_id, "employee_id": 2, "paired_time": current_time}
                })
                paired = True
            
            if paired:
                self.events_to_emit = new_events
                self.hold_in("EMIT_EVENTS", 0.0)
            else:
                self._schedule_next_internal_event()

        elif self.phase == "SERVICE_COMPLETE_1":
            # Employee 1 finished service
            events = []
            events.append({
                "event": "client_served",
                "entity_type": "employee",
                "entity": "Employee_1",
                "payload": {
                    "client_id": self.employee_1_client_id,
                    "employee_id": 1,
                    "arrived": self.employee_1_arrival_time,
                    "dispatched": current_time,
                    "delay": current_time - self.employee_1_arrival_time
                }
            })
            events.append({
                "event": "employee_available",
                "entity_type": "employee",
                "entity": "Employee_1",
                "payload": {"employee_id": 1}
            })
            
            self.employee_1_available = True
            self.employee_1_client_id = None
            self.employee_1_arrival_time = None
            self.next_service_end_time_1 = float('inf')
            
            self.events_to_emit = events
            self.hold_in("EMIT_EVENTS", 0.0)

        elif self.phase == "SERVICE_COMPLETE_2":
            # Employee 2 finished service
            events = []
            events.append({
                "event": "client_served",
                "entity_type": "employee",
                "entity": "Employee_2",
                "payload": {
                    "client_id": self.employee_2_client_id,
                    "employee_id": 2,
                    "arrived": self.employee_2_arrival_time,
                    "dispatched": current_time,
                    "delay": current_time - self.employee_2_arrival_time
                }
            })
            events.append({
                "event": "employee_available",
                "entity_type": "employee",
                "entity": "Employee_2",
                "payload": {"employee_id": 2}
            })
            
            self.employee_2_available = True
            self.employee_2_client_id = None
            self.employee_2_arrival_time = None
            self.next_service_end_time_2 = float('inf')
            
            self.events_to_emit = events
            self.hold_in("EMIT_EVENTS", 0.0)

    def _schedule_next_internal_event(self):
        """Determine the next event (arrival or service completion) and schedule it."""
        current_time = get_current_time()
        
        times = []
        if self.next_arrival_time <= self.simulation_horizon:
            times.append(self.next_arrival_time)
        if self.next_service_end_time_1 != float('inf'):
            times.append(self.next_service_end_time_1)
        if self.next_service_end_time_2 != float('inf'):
            times.append(self.next_service_end_time_2)
            
        if not times:
            self.passivate("PASSIVE")
            return

        next_event_time = min(times)
        delay = next_event_time - current_time
        
        # Prioritize service completions if times are equal to free resources for arrivals
        if next_event_time == self.next_service_end_time_1:
            self.hold_in("SERVICE_COMPLETE_1", delay)
        elif next_event_time == self.next_service_end_time_2:
            self.hold_in("SERVICE_COMPLETE_2", delay)
        else:
            self.hold_in("PROCESS_ARRIVAL", delay)

    def exit(self):
        pass