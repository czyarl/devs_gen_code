from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json
import sys


class ReceptionDesk(Atomic):
    def __init__(self, name: str, parent: Coupled | None, queue_capacity: int, checkin_time: float):
        super().__init__(name)
        self.parent = parent
        self.queue_capacity = queue_capacity
        self.checkin_time = checkin_time
        self.add_in_port(Port(dict, "newcust"))
        self.add_out_port(Port(dict, "cust"))
        self.waiting_queue = []
        self.total_customers = 0
        self.processing_customer = None

    def initialize(self):
        self.waiting_queue = []
        self.total_customers = 0
        self.processing_customer = None
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return

        # Handle new customer arrivals
        for packet in self.input["newcust"].values:
            if len(self.waiting_queue) < self.queue_capacity:
                customer_id = packet["payload"]["customer_id"]
                self.waiting_queue.append(customer_id)
                self.total_customers += 1
                # Log state change
                record = {
                    "time": get_current_time(),
                    "type": "state",
                    "model": "reception",
                    "field": "total customers num",
                    "value": str(self.total_customers)
                }
                print(json.dumps(record), flush=True)
                # Start processing if not already processing
                if self.phase == "IDLE":
                    self._start_processing()
            else:
                # Customer ignored due to full queue
                pass
        # If we're idle and have customers to process, start processing
        if self.phase == "IDLE" and self.waiting_queue:
            self._start_processing()

    def _start_processing(self):
        if self.waiting_queue:
            self.processing_customer = self.waiting_queue[0]
            self.hold_in("PROCESSING", self.checkin_time)
        else:
            self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "PROCESSING" and self.processing_customer is not None:
            # Prepare customer for forwarding
            customer_event = {
                "time": get_current_time(),
                "event_type": "newcust",
                "payload": {"customer_id": self.processing_customer}
            }
            self.output["cust"].add(customer_event)
            # Log message
            record = {
                "time": get_current_time(),
                "type": "message",
                "model": "reception",
                "port": "cust",
                "content": "newcust"
            }
            print(json.dumps(record), flush=True)

    def deltint(self):
        if self.phase == "PROCESSING" and self.processing_customer is not None:
            # Remove processed customer from queue
            if self.waiting_queue and self.waiting_queue[0] == self.processing_customer:
                self.waiting_queue.pop(0)
            self.processing_customer = None
            # Continue processing next customer if available
            if self.waiting_queue:
                self._start_processing()
            else:
                self.passivate("IDLE")

    def exit(self):
        pass