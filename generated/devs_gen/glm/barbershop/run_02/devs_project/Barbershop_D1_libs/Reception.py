import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Reception(Atomic):
    """Manages the customer waiting queue with a fixed capacity of 8."""

    def __init__(self, name: str, parent: Coupled | None, queue_capacity: int, processing_time: float):
        super().__init__(name)
        self.parent = parent
        self.queue_capacity = queue_capacity
        self.processing_time = processing_time

        self.add_in_port(Port(str, "in_cust"))
        self.add_in_port(Port(str, "done_in"))
        self.add_out_port(Port(str, "cust"))

        self.queue = []
        self.total_customers_num = 0
        self.checkhair_available = True
        self.payload_to_send = None

    def _write_state(self, field: str, value):
        print(json.dumps({
            "time": get_current_time(),
            "type": "state",
            "model": "reception",
            "field": field,
            "value": value
        }), flush=True)

    def _write_message(self, port: str, content: str):
        print(json.dumps({
            "time": get_current_time(),
            "type": "message",
            "model": "reception",
            "port": port,
            "content": content
        }), flush=True)

    def initialize(self):
        self.queue = []
        self.total_customers_num = 0
        self.checkhair_available = True
        self.payload_to_send = None
        self.passivate("IDLE")

    def deltext(self, e):
        # If we were processing a customer, reduce the remaining time
        if self.phase == "PROCESSING":
            self.continuef(e)

        # Process incoming 'newcust' events
        for val in self.input["in_cust"].values:
            if val == "newcust":
                if self.total_customers_num < self.queue_capacity:
                    self.queue.append(val)
                    self.total_customers_num += 1
                    self._write_state("total customers num", self.total_customers_num)
                    
                    # If we were idle, start processing the first customer
                    if self.phase == "IDLE":
                        self.hold_in("PROCESSING", self.processing_time)
                # If queue is full, ignore arrival

        # Process incoming 'done' events
        for val in self.input["done_in"].values:
            if val == "done":
                self.checkhair_available = True
                self.total_customers_num -= 1
                self._write_state("total customers num", self.total_customers_num)

                # If we are waiting to send a customer (because CheckHair was busy),
                # and we just became available, we should try to send immediately.
                # However, in DEVS, we cannot output from deltext. 
                # We schedule an internal transition with 0 delay to handle the output.
                if self.phase == "WAITING_FOR_AVAILABILITY":
                    self.hold_in("TRY_SEND", 0.0)
                # If we were processing and the queue is not empty, we continue processing.
                # If we were idle, we stay idle.

    def lambdaf(self):
        if self.phase == "SENDING" and self.payload_to_send is not None:
            self.output["cust"].add(self.payload_to_send)
            self._write_message("cust", self.payload_to_send)

    def deltint(self):
        if self.phase == "PROCESSING":
            # Processing time for the head customer elapsed.
            if self.checkhair_available and self.queue:
                # Prepare to send the customer
                self.payload_to_send = self.queue.pop(0)
                # We don't change total_customers_num yet, as per requirements:
                # "marks CheckHair as unavailable, and begins processing the next customer"
                # The count decrement happens on 'done' signal.
                self.checkhair_available = False
                self.hold_in("SENDING", 0.0)
            else:
                # CheckHair is not available, wait indefinitely until it is.
                # We stay in a phase that indicates we are ready to send but blocked.
                # We use a specific phase to distinguish from IDLE.
                self.passivate("WAITING_FOR_AVAILABILITY")

        elif self.phase == "SENDING":
            self.payload_to_send = None
            
            # Start processing the next customer in the queue if any
            if self.queue:
                self.hold_in("PROCESSING", self.processing_time)
            else:
                self.passivate("IDLE")

        elif self.phase == "TRY_SEND":
            # Triggered by deltext when 'done' arrived while we were waiting.
            # We are now available, so try to send the head of the queue.
            if self.queue:
                self.payload_to_send = self.queue.pop(0)
                self.checkhair_available = False
                self.hold_in("SENDING", 0.0)
            else:
                # Should not happen if logic is correct, but safe fallback
                self.passivate("IDLE")

        else:
            # Should not be reached if logic covers all phases
            self.passivate("IDLE")

    def exit(self):
        pass