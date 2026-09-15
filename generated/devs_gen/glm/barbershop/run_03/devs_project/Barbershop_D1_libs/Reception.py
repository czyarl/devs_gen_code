import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Reception(Atomic):
    """
    Manages a FIFO waiting queue with a maximum capacity of 8.
    Processes customers for a fixed duration of 5 seconds (check-in).
    Coordinates with CheckHair to hand off customers when available.
    """

    def __init__(self, name: str, parent: Coupled | None, capacity: int, process_time: float):
        super().__init__(name)
        self.parent = parent
        self.capacity = capacity
        self.process_time = process_time

        # Define ports
        self.add_in_port(Port(str, "arrival_in"))
        self.add_in_port(Port(str, "service_done"))
        self.add_out_port(Port(str, "cust"))

        # Internal state
        self.queue = []  # FIFO queue of waiting customers (excluding the one being processed)
        self.checkhair_available = True
        self.processing_customer = None  # Customer currently being processed (check-in)
        self.ready_customer = None  # Customer processed but waiting for CheckHair availability

    def _log_state(self, field: str, value):
        """Writes a state change JSONL record to stdout."""
        record = {
            "time": get_current_time(),
            "type": "state",
            "model": "reception",
            "field": field,
            "value": value
        }
        print(json.dumps(record), flush=True)

    def _log_message(self, port: str, content: str):
        """Writes a communication event JSONL record to stdout."""
        record = {
            "time": get_current_time(),
            "type": "message",
            "model": "reception",
            "port": port,
            "content": content
        }
        print(json.dumps(record), flush=True)

    def _get_total_customers(self) -> int:
        """Calculates the total number of customers currently in the system."""
        count = len(self.queue)
        if self.processing_customer is not None:
            count += 1
        if self.ready_customer is not None:
            count += 1
        return count

    def initialize(self):
        self.queue = []
        self.checkhair_available = True
        self.processing_customer = None
        self.ready_customer = None
        self.passivate("IDLE")

    def deltext(self, e):
        # If we were processing, we need to account for elapsed time
        if self.phase == "PROCESSING":
            self.continuef(e)

        # Handle input from arrival_in
        for _ in self.input["arrival_in"].values:
            # Requirement: If Queue < 8: Accept customer, increment queue count.
            # If Queue = 8: Ignore the new customer.
            if self._get_total_customers() < self.capacity:
                self.queue.append("newcust")
                # Log state change for queue size
                self._log_state("total customers num", str(self._get_total_customers()))

        # Handle input from service_done
        for _ in self.input["service_done"].values:
            # Upon receiving 'service_done' while idle or processing, updates the CheckHair availability flag to true.
            self.checkhair_available = True

            # If we have a ready customer waiting for CheckHair, we can hand them off immediately.
            # If we are in READY_WAIT state, schedule immediate handoff.
            if self.phase == "READY_WAIT":
                self.hold_in("HANDOFF", 0.0)
            # If we are IDLE but somehow have a ready_customer (e.g. edge case), schedule handoff
            elif self.phase == "IDLE" and self.ready_customer is not None:
                self.hold_in("HANDOFF", 0.0)

        # If we are IDLE and have customers in the queue, start processing the first one.
        if self.phase == "IDLE":
            if self.queue:
                self.processing_customer = self.queue.pop(0)
                # Log state change for queue size (decreased because one moved to processing)
                self._log_state("total customers num", str(self._get_total_customers()))
                self.hold_in("PROCESSING", self.process_time)
            else:
                self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "HANDOFF":
            # Send the ready customer to CheckHair
            if self.ready_customer is not None:
                self.output["cust"].add(self.ready_customer)
                self._log_message("cust", self.ready_customer)
                # Mark CheckHair as unavailable
                self.checkhair_available = False

    def deltint(self):
        if self.phase == "PROCESSING":
            # Processing finished
            # Move processing_customer to ready_customer
            self.ready_customer = self.processing_customer
            self.processing_customer = None

            # Check if CheckHair is available
            if self.checkhair_available:
                # Handoff immediately
                self.hold_in("HANDOFF", 0.0)
            else:
                # Wait for CheckHair
                self.passivate("READY_WAIT")

        elif self.phase == "HANDOFF":
            # Handoff completed (output sent in lambdaf)
            self.ready_customer = None

            # Check if there are more customers in the queue
            if self.queue:
                self.processing_customer = self.queue.pop(0)
                # Log state change for queue size
                self._log_state("total customers num", str(self._get_total_customers()))
                self.hold_in("PROCESSING", self.process_time)
            else:
                self.passivate("IDLE")

        else:
            # Should not be reached for IDLE or READY_WAIT unless logic changes
            self.passivate(self.phase)

    def exit(self):
        pass