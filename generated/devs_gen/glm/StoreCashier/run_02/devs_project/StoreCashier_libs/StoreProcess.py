import json
import sys
import random
import math
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class StoreProcess(Atomic):
    """
    Atomic DEVS model implementing the entire store scenario logic internally:
    generating clients using the specified distribution, managing a FIFO queue,
    simulating two employees with their specific service distributions, and
    emitting the four required JSONL event types to stdout.
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        client_mean: float,
        client_stddev: float,
        employee_1_mean: float,
        employee_1_stddev: float,
        employee_2_mean: float,
        employee_2_stddev: float,
        seed: int | None = None
    ):
        super().__init__(name)
        self.parent = parent
        
        # Parameters
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.employee_1_mean = employee_1_mean
        self.employee_1_stddev = employee_1_stddev
        self.employee_2_mean = employee_2_mean
        self.employee_2_stddev = employee_2_stddev
        self.seed = seed

        # Random number generator
        self.rng = random.Random(seed)

        # Internal State
        self.next_client_id = 1
        self.queue = []  # List of dicts: {'client_id': int, 'arrival_time': float}
        
        # Employees state
        # None means idle, otherwise dict with client info
        self.employee_1_state = None 
        self.employee_2_state = None

        # Event scheduling helpers
        self.next_arrival_time = 0.0
        self.next_service_completion_time = float('inf')
        
        # Payloads for output events (simulated via stdout in lambdaf or deltint)
        # Since this is an atomic model with no ports, we handle IO in the transition methods.
        # We use specific phases to trigger events.
        
        # No input or output ports required by contract
        # self.add_in_port(...)
        # self.add_out_port(...)

    def _format_time_str(self, time_val: float) -> str:
        """Format simulation time to HH:MM:SS:mmm."""
        total_seconds = int(time_val)
        milliseconds = int((time_val - total_seconds) * 1000)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"

    def _write_jsonl(self, record: dict):
        """Helper to write JSONL to stdout."""
        # Ensure time_str is populated if not already
        if "time_str" not in record:
            record["time_str"] = self._format_time_str(record["time"])
        print(json.dumps(record), flush=True)

    def _generate_client(self):
        """Generate a new client and schedule next generation."""
        current_time = get_current_time()
        
        client_id = self.next_client_id
        arrival_time = current_time
        
        # Create client record
        client = {"client_id": client_id, "arrival_time": arrival_time}
        
        # Emit client_generated event
        self._write_jsonl({
            "time": current_time,
            "time_str": self._format_time_str(current_time),
            "event": "client_generated",
            "entity_type": "client_generator",
            "entity": "ClientGenerator",
            "payload": {
                "client_id": client_id,
                "arrival_time": arrival_time
            }
        })
        
        # Add to queue
        self.queue.append(client)
        
        # Increment ID
        self.next_client_id += 1
        
        # Calculate next inter-arrival time
        # Constraint: 0 <= interval <= client_mean + 5 * client_stddev
        max_interval = self.client_mean + 5 * self.client_stddev
        interval = 0.0
        if self.client_stddev > 0:
            interval = self.rng.gauss(self.client_mean, self.client_stddev)
        else:
            interval = self.client_mean
            
        interval = max(0.0, min(interval, max_interval))
        
        self.next_arrival_time = current_time + interval

    def _try_pair_client(self):
        """Try to pair a waiting client with an available employee."""
        if not self.queue:
            return

        # Check Employee 1
        if self.employee_1_state is None:
            client = self.queue.pop(0)
            self._assign_employee(1, client)
            # If still queue and other employee free, try again immediately (same time step)
            if self.queue and self.employee_2_state is None:
                client = self.queue.pop(0)
                self._assign_employee(2, client)
            return

        # Check Employee 2
        if self.employee_2_state is None:
            client = self.queue.pop(0)
            self._assign_employee(2, client)
            return

    def _assign_employee(self, emp_id: int, client: dict):
        """Assign client to employee and schedule service completion."""
        current_time = get_current_time()
        
        # Emit client_paired event
        self._write_jsonl({
            "time": current_time,
            "time_str": self._format_time_str(current_time),
            "event": "client_paired",
            "entity_type": "queue",
            "entity": "Queue",
            "payload": {
                "client_id": client["client_id"],
                "employee_id": emp_id,
                "paired_time": current_time
            }
        })
        
        # Determine service duration
        # Constraint: mean - 3*stddev <= duration <= mean + 3*stddev
        if emp_id == 1:
            mean = self.employee_1_mean
            stddev = self.employee_1_stddev
        else:
            mean = self.employee_2_mean
            stddev = self.employee_2_stddev
            
        duration = 0.0
        if stddev > 0:
            duration = self.rng.gauss(mean, stddev)
        else:
            duration = mean
            
        min_duration = mean - 3 * stddev
        max_duration = mean + 3 * stddev
        duration = max(min_duration, min(duration, max_duration))
        
        # Update employee state
        service_info = {
            "client": client,
            "start_time": current_time,
            "duration": duration,
            "end_time": current_time + duration
        }
        
        if emp_id == 1:
            self.employee_1_state = service_info
        else:
            self.employee_2_state = service_info
            
        # Update next service completion time
        self._recalc_next_service_time()

    def _recalc_next_service_time(self):
        """Find the earliest service completion time."""
        t1 = float('inf')
        t2 = float('inf')
        
        if self.employee_1_state:
            t1 = self.employee_1_state["end_time"]
        if self.employee_2_state:
            t2 = self.employee_2_state["end_time"]
            
        self.next_service_completion_time = min(t1, t2)

    def _complete_service(self):
        """Complete service for the employee whose timer expired."""
        current_time = get_current_time()
        
        # Determine who finished (handle potential floating point ties)
        emp_to_finish = None
        
        # Check if times match current_time (within tolerance)
        finished_1 = self.employee_1_state and abs(self.employee_1_state["end_time"] - current_time) < 1e-9
        finished_2 = self.employee_2_state and abs(self.employee_2_state["end_time"] - current_time) < 1e-9
        
        if finished_1 and finished_2:
            # Both finished at same time. Pick one arbitrarily (e.g., 1 then 2)
            # We will handle one now, the other will be handled in the next cycle if we reschedule correctly,
            # or we can handle both immediately if logic permits.
            # However, DEVS semantics usually process one event at a time.
            # If we process 1, we set state to None, recalc time. The other time will still be current_time.
            # So we loop or rely on deltint being called again immediately if sigma=0.
            # Let's pick 1.
            emp_to_finish = 1
        elif finished_1:
            emp_to_finish = 1
        elif finished_2:
            emp_to_finish = 2
            
        if emp_to_finish is None:
            # Should not happen if logic is correct
            self.passivate("IDLE")
            return

        # Retrieve info
        if emp_to_finish == 1:
            info = self.employee_1_state
            self.employee_1_state = None
        else:
            info = self.employee_2_state
            self.employee_2_state = None
            
        client = info["client"]
        arrived = client["arrival_time"]
        dispatched = current_time
        delay = dispatched - arrived
        
        # Emit client_served event
        self._write_jsonl({
            "time": current_time,
            "time_str": self._format_time_str(current_time),
            "event": "client_served",
            "entity_type": "employee",
            "entity": f"Employee_{emp_to_finish}",
            "payload": {
                "client_id": client["client_id"],
                "employee_id": emp_to_finish,
                "arrived": arrived,
                "dispatched": dispatched,
                "delay": delay
            }
        })
        
        # Emit employee_available event
        self._write_jsonl({
            "time": current_time,
            "time_str": self._format_time_str(current_time),
            "event": "employee_available",
            "entity_type": "employee",
            "entity": f"Employee_{emp_to_finish}",
            "payload": {
                "employee_id": emp_to_finish
            }
        })
        
        # Recalculate next service time
        self._recalc_next_service_time()
        
        # Try to pair waiting clients immediately
        self._try_pair_client()
        
        # Schedule next internal event
        self._schedule_next()

    def _schedule_next(self):
        """Determine the next event time and phase."""
        t_arrival = self.next_arrival_time
        t_service = self.next_service_completion_time
        
        if t_arrival == float('inf') and t_service == float('inf'):
            self.passivate("IDLE")
        else:
            next_event_time = min(t_arrival, t_service)
            sigma = next_event_time - get_current_time()
            
            # Determine phase based on what happens next
            # If arrival and service happen at same time, we need to decide order.
            # Requirements: "Events must be emitted in nondecreasing simulation-time order."
            # Usually generation happens then pairing then service.
            # If t_arrival == t_service:
            #   If we generate, we might pair, which might start a service.
            #   If we complete service, we free employee, we might pair.
            #   Let's prioritize ARRIVAL if they are equal, as it adds new work.
            
            if t_arrival <= t_service:
                self.hold_in("GENERATE", sigma)
            else:
                self.hold_in("SERVICE", sigma)

    def initialize(self):
        """Initialize the model."""
        # Employees are initially available at t=0.0
        # Emit initial availability events
        t0 = 0.0
        self._write_jsonl({
            "time": t0,
            "time_str": self._format_time_str(t0),
            "event": "employee_available",
            "entity_type": "employee",
            "entity": "Employee_1",
            "payload": {"employee_id": 1}
        })
        self._write_jsonl({
            "time": t0,
            "time_str": self._format_time_str(t0),
            "event": "employee_available",
            "entity_type": "employee",
            "entity": "Employee_2",
            "payload": {"employee_id": 2}
        })
        
        # First client is generated at t=0.0
        # We schedule the generation immediately.
        self.next_arrival_time = 0.0
        self.next_service_completion_time = float('inf')
        
        self._schedule_next()

    def deltext(self, e: float):
        """Handle external inputs (none for this model)."""
        # No input ports, so this should not be called with data.
        # But we must handle elapsed time if it were.
        self.continuef(e)

    def lambdaf(self):
        """Output function (no DEVS ports, but logic might be placed here)."""
        # Since we have no output ports, we don't need to do anything here.
        # All external IO (stdout) is handled in deltint or initialize.
        pass

    def deltint(self):
        """Internal transition."""
        if self.phase == "GENERATE":
            self._generate_client()
            # After generation, try to pair
            self._try_pair_client()
            # Schedule next
            self._schedule_next()
            
        elif self.phase == "SERVICE":
            self._complete_service()
            # _complete_service handles pairing and rescheduling internally
            
        else:
            self.passivate("IDLE")

    def exit(self):
        """Cleanup."""
        pass