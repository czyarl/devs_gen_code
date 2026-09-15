"""ReceptionDesk model implementing the barbershop reception logic."""

import json
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ReceptionDesk(Atomic):
    """Manages a waiting queue for customers arriving at the reception desk."""

    def __init__(self, name: str, parent: Coupled | None, queue_capacity: int, check_in_time: float):
        super().__init__(name)
        self.parent = parent
        self.queue_capacity = queue_capacity
        self.check_in_time = check_in_time
        self.add_in_port(Port(str, "cust"))
        self.add_out_port(Port(str, "cust"))
        self.queue = deque()
        self.current_customer = None
        self.payload_to_send = None
        self.is_busy = False

    def _write_state_change(self, field: str, value) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "type": "state",
            "model": "reception",
            "field": field,
            "value": value,
        }), flush=True)

    def _write_message(self, port: str, content: str) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "type": "message",
            "model": "reception",
            "port": port,
            "content": content,
        }), flush=True)

    def initialize(self):
        self.queue = deque()
        self.current_customer = None
        self.payload_to_send = None
        self.is_busy = False
        self._write_state_change("total customers num", str(len(self.queue)))
        self.passivate("IDLE")

    def deltext(self, e):
        # Handle incoming customer
        for cust in self.input["cust"].values:
            if len(self.queue) < self.queue_capacity:
                self.queue.append(cust)
                self._write_state_change("total customers num", str(len(self.queue)))
                self._write_message("cust", "newcust")
            else:
                # Ignore the customer if queue is full
                pass

        # If we're in PROCESSING phase, continue processing
        if self.phase == "PROCESSING":
            self.continuef(e)
            return

        # If we're idle and have customers, start processing
        if self.phase == "IDLE" and self.queue:
            self._start_processing()

    def _start_processing(self) -> None:
        if not self.queue:
            return
        self.current_customer = self.queue.popleft()
        self.is_busy = True
        self._write_state_change("total customers num", str(len(self.queue)))
        self.hold_in("PROCESSING", self.check_in_time)

    def lambdaf(self):
        if self.phase == "OUTPUT_READY" and self.payload_to_send is not None:
            self.output["cust"].add(self.payload_to_send)
            self.payload_to_send = None

    def deltint(self):
        if self.phase == "PROCESSING":
            # Customer has been processed, send to next phase
            self.payload_to_send = "newcust"
            self.hold_in("OUTPUT_READY", 0.0)
        elif self.phase == "OUTPUT_READY":
            # Finished sending customer, check if we have more to process
            self.current_customer = None
            self.is_busy = False
            self.payload_to_send = None
            if self.queue:
                self._start_processing()
            else:
                self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass