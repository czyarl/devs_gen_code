"""ReceptionDesk model implementing the barbershop reception queue logic."""

import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class ReceptionDesk(Atomic):
    """Manages a waiting area queue for up to 8 customers at the reception desk."""

    def __init__(self, name: str, parent: Coupled | None, queue_capacity: int, checkin_duration: float):
        super().__init__(name)
        self.parent = parent
        self.queue_capacity = queue_capacity
        self.checkin_duration = checkin_duration
        self.add_in_port(Port(dict, "newcust"))
        self.add_in_port(Port(dict, "done"))
        self.add_out_port(Port(dict, "cust"))
        self.queue = deque()
        self.processing_customer = None
        self.is_processing = False

    def initialize(self):
        self.queue = deque()
        self.processing_customer = None
        self.is_processing = False
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return

        # Handle new customer arrival
        for packet in self.input["newcust"].values:
            if len(self.queue) < self.queue_capacity:
                self.queue.append(packet)
                self._emit_state_change()
            # If queue is full, ignore the customer

        # Handle completion signal from HairInspectionPhase
        for packet in self.input["done"].values:
            # This signal indicates the customer has finished the full service
            # and the inspection phase is now available again
            pass  # We don't need to store this, just process it

        # Check if we can start processing
        if not self.is_processing and self.queue:
            self._start_processing()

    def _start_processing(self):
        if not self.queue:
            self.passivate("IDLE")
            return

        self.processing_customer = self.queue[0]
        self.is_processing = True
        self.hold_in("PROCESSING", self.checkin_duration)

    def lambdaf(self):
        if self.phase == "PROCESSING":
            # Customer is being processed, send to HairInspectionPhase
            if self.processing_customer:
                self.output["cust"].add(self.processing_customer)
                # Emit message record
                print(json.dumps({
                    "time": get_current_time(),
                    "type": "message",
                    "model": "reception",
                    "port": "cust",
                    "content": "newcust"
                }), flush=True)

    def deltint(self):
        if self.phase == "PROCESSING":
            # Finish processing the customer
            if self.processing_customer:
                self.queue.popleft()
                self._emit_state_change()
                self.processing_customer = None
                self.is_processing = False

            # Check if there are more customers to process
            if self.queue:
                self._start_processing()
            else:
                self.passivate("IDLE")

    def _emit_state_change(self):
        print(json.dumps({
            "time": get_current_time(),
            "type": "state",
            "model": "reception",
            "field": "total customers num",
            "value": str(len(self.queue))
        }), flush=True)

    def exit(self):
        pass