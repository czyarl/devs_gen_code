import json
import random
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class CashierProcess(Atomic):
    """
    Orchestrates the entire cashier workflow as a self-contained discrete event simulation.
    Manages client generation, FIFO queue, and two employees.
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
        seed: int | None = None,
    ):
        super().__init__(name)
        self.parent = parent

        # Configuration
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.employee_1_mean = employee_1_mean
        self.employee_1_stddev = employee_1_stddev
        self.employee_2_mean = employee_2_mean
        self.employee_2_stddev = employee_2_stddev

        # Random number generator
        self.rng = random.Random(seed)

        # Simulation Horizon
        self.simulation_horizon = float('inf')

        # State: Client Generation
        self.next_client_id = 1
        self.next_arrival_time = 0.0

        # State: Queue
        self.queue = []  # List of dicts: {'client_id': int, 'arrival_time': float}

        # State: Employees
        # employee_status: 0 = idle, 1 = busy
        self.employee_1_status = 0
        self.employee_1_finish_time = float('inf')
        self.employee_1_current_client = None

        self.employee_2_status = 0
        self.employee_2_finish_time = float('inf')
        self.employee_2_current_client = None

        # Output payload for lambdaf (not strictly needed as no DEVS ports, but good practice if extended)
        self.payload_to_send = None

    def _sample_inter_arrival(self) -> float:
        """Sample inter-arrival time clamped to 0 <= interval <= mean + 5*stddev."""
        if self.client_stddev == 0.0:
            return self.client_mean
        
        # Using normal distribution
        val = self.rng.normalvariate(self.client_mean, self.client_stddev)
        upper_bound = self.client_mean + 5 * self.client_stddev
        return max(0.0, min(val, upper_bound))

    def _sample_service_duration(self, mean: float, stddev: float) -> float:
        """Sample service duration clamped to mean - 3*stddev <= duration <= mean + 3*stddev."""
        if stddev == 0.0:
            return mean
        
        val = self.rng.normalvariate(mean, stddev)
        lower_bound = mean - 3 * stddev
        upper_bound = mean + 3 * stddev
        return max(lower_bound, min(val, upper_bound))

    def _format_time_str(self, time_val: float) -> str:
        """Format simulation time to HH:MM:SS:mmm."""
        # time_val is in seconds
        total_millis = int(time_val * 1000)
        hours = total_millis // 3_600_000
        minutes = (total_millis % 3_600_000) // 60_000
        seconds = (total_millis % 60_000) // 1_000
        millis = total_millis % 1_000
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{millis:03d}"

    def _write_event(self, event_type: str, entity_type: str, entity: str, payload: dict) -> None:
        """Write JSONL event to stdout."""
        current_time = get_current_time()
        record = {
            "time": current_time,
            "time_str": self._format_time_str(current_time),
            "event": event_type,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload
        }
        print(json.dumps(record), flush=True)

    def initialize(self):
        # Initialize state
        self.queue = []
        self.next_client_id = 1
        self.next_arrival_time = 0.0
        
        self.employee_1_status = 0
        self.employee_1_finish_time = float('inf')
        self.employee_1_current_client = None
        
        self.employee_2_status = 0
        self.employee_2_finish_time = float('inf')
        self.employee_2_current_client = None

        # Schedule initial availability events at t=0.0
        self.hold_in("INIT_AVAILABILITY", 0.0)

    def deltext(self, e):
        # This model has no input ports, so deltext is not used for external DEVS events.
        # However, the simulator might call it. We just continue the current phase.
        if self.phase != "passive":
            self.continuef(e)

    def lambdaf(self):
        # No DEVS output ports are defined for this Atomic model.
        # All output is external IO (stdout) handled within deltint/logic helpers.
        pass

    def _try_pair_client(self, employee_id: int):
        """Try to pair a waiting client with a specific employee."""
        if employee_id == 1:
            if self.employee_1_status == 0 and self.queue:
                client = self.queue.pop(0) # FIFO
                self.employee_1_status = 1
                self.employee_1_current_client = client
                
                # Emit client_paired
                self._write_event(
                    "client_paired",
                    "queue",
                    "Queue",
                    {
                        "client_id": client["client_id"],
                        "employee_id": 1,
                        "paired_time": get_current_time()
                    }
                )
                
                # Schedule service completion
                duration = self._sample_service_duration(self.employee_1_mean, self.employee_1_stddev)
                self.employee_1_finish_time = get_current_time() + duration
                
                # Update sigma to next event (min of arrival and finish times)
                self._schedule_next_event()
                return True
        elif employee_id == 2:
            if self.employee_2_status == 0 and self.queue:
                client = self.queue.pop(0) # FIFO
                self.employee_2_status = 1
                self.employee_2_current_client = client
                
                # Emit client_paired
                self._write_event(
                    "client_paired",
                    "queue",
                    "Queue",
                    {
                        "client_id": client["client_id"],
                        "employee_id": 2,
                        "paired_time": get_current_time()
                    }
                )
                
                # Schedule service completion
                duration = self._sample_service_duration(self.employee_2_mean, self.employee_2_stddev)
                self.employee_2_finish_time = get_current_time() + duration
                
                # Update sigma to next event
                self._schedule_next_event()
                return True
        return False

    def _schedule_next_event(self):
        """Determine the next event time and set phase/sigma."""
        now = get_current_time()
        
        # Calculate next arrival
        next_arrival = self.next_arrival_time
        
        # Calculate next service completion
        next_service = min(self.employee_1_finish_time, self.employee_2_finish_time)
        
        # Determine the earliest event
        next_event_time = min(next_arrival, next_service)
        
        # Check horizon
        if next_event_time >= self.simulation_horizon:
            self.passivate("FINISHED")
            return

        # If arrival is the next event
        if next_arrival <= next_service:
            sigma = next_arrival - now
            self.hold_in("GENERATE_CLIENT", sigma)
        else:
            # Service completion is next
            sigma = next_service - now
            self.hold_in("SERVICE_COMPLETE", sigma)

    def deltint(self):
        now = get_current_time()

        if self.phase == "INIT_AVAILABILITY":
            # This phase is used to emit initial availability events at t=0
            # We emit for both, then move to GENERATE_CLIENT (which is also at t=0)
            
            self._write_event(
                "employee_available",
                "employee",
                "Employee_1",
                {"employee_id": 1}
            )
            self._write_event(
                "employee_available",
                "employee",
                "Employee_2",
                {"employee_id": 2}
            )
            
            # Transition to generation logic immediately
            self.hold_in("GENERATE_CLIENT", 0.0)

        elif self.phase == "GENERATE_CLIENT":
            # Emit client_generated
            self._write_event(
                "client_generated",
                "client_generator",
                "ClientGenerator",
                {
                    "client_id": self.next_client_id,
                    "arrival_time": now
                }
            )
            
            # Add to queue
            self.queue.append({
                "client_id": self.next_client_id,
                "arrival_time": now
            })
            self.next_client_id += 1
            
            # Schedule next arrival
            interval = self._sample_inter_arrival()
            self.next_arrival_time = now + interval
            
            # Try to pair with idle employees
            # Priority isn't specified, but we can try Employee 1 then 2
            self._try_pair_client(1)
            self._try_pair_client(2)
            
            # If no pairing happened (or happened), we need to reschedule based on next event
            # If we just paired, the service completion time was updated inside _try_pair_client
            # We just need to ensure the next event is set correctly.
            # _schedule_next_event handles the logic of comparing arrival vs service times.
            self._schedule_next_event()

        elif self.phase == "SERVICE_COMPLETE":
            # Determine which employee(s) finished
            # Note: In strict DEVS, only one event happens at a time unless confluent.
            # Here we check which one triggered this.
            
            finished_1 = (abs(now - self.employee_1_finish_time) < 1e-9) and self.employee_1_status == 1
            finished_2 = (abs(now - self.employee_2_finish_time) < 1e-9) and self.employee_2_status == 1
            
            if finished_1:
                client = self.employee_1_current_client
                # Emit client_served
                self._write_event(
                    "client_served",
                    "employee",
                    "Employee_1",
                    {
                        "client_id": client["client_id"],
                        "employee_id": 1,
                        "arrived": client["arrival_time"],
                        "dispatched": now,
                        "delay": now - client["arrival_time"]
                    }
                )
                
                # Reset Employee 1
                self.employee_1_status = 0
                self.employee_1_current_client = None
                self.employee_1_finish_time = float('inf')
                
                # Emit employee_available
                self._write_event(
                    "employee_available",
                    "employee",
                    "Employee_1",
                    {"employee_id": 1}
                )
                
                # Try to pair immediately
                self._try_pair_client(1)

            if finished_2:
                client = self.employee_2_current_client
                # Emit client_served
                self._write_event(
                    "client_served",
                    "employee",
                    "Employee_2",
                    {
                        "client_id": client["client_id"],
                        "employee_id": 2,
                        "arrived": client["arrival_time"],
                        "dispatched": now,
                        "delay": now - client["arrival_time"]
                    }
                )
                
                # Reset Employee 2
                self.employee_2_status = 0
                self.employee_2_current_client = None
                self.employee_2_finish_time = float('inf')
                
                # Emit employee_available
                self._write_event(
                    "employee_available",
                    "employee",
                    "Employee_2",
                    {"employee_id": 2}
                )
                
                # Try to pair immediately
                self._try_pair_client(2)
            
            # If both finished at exactly same time (unlikely with float but possible), logic above handles both.
            
            # Reschedule next event
            self._schedule_next_event()

        elif self.phase == "FINISHED":
            self.passivate("FINISHED")

    def exit(self):
        pass