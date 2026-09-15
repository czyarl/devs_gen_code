"""Atomic DEVS model for LoadingQueue as specified in the locked contract."""

import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class LoadingQueue(Atomic):
    """Maintains a queue of incoming pallets, monitors their expiration times,
    and notifies the Fleet Coordinator when pallets are claimed.
    Writes 'pallet_queued' and 'pallet_expired' events to stdout.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "pallet_in"))
        self.add_in_port(Port(dict, "assignment_request_in"))
        self.add_out_port(Port(dict, "pallet_claimed_out"))
        self.queue = deque()
        self.total_expired = 0
        self.prepared_pallet = None

    def initialize(self):
        self.queue = deque()
        self.total_expired = 0
        self.prepared_pallet = None
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "OUTPUT_READY":
            self.continuef(e)
            return

        # Process incoming pallets
        for pallet in self.input["pallet_in"].values:
            self._enqueue_pallet(pallet)

        # Process assignment requests
        for request in self.input["assignment_request_in"].values:
            self._handle_assignment_request(request)

        # Check for expired pallets
        self._check_expired_pallets()

    def _enqueue_pallet(self, pallet: dict) -> None:
        """Add a pallet to the queue and emit a pallet_queued event."""
        self.queue.append(pallet)
        queue_size = len(self.queue)
        event_payload = {
            "pallet_id": pallet["pallet_id"],
            "queue_size": queue_size
        }
        record = {
            "time": get_current_time(),
            "entity": "queue",
            "event": "pallet_queued",
            "payload": event_payload
        }
        print(json.dumps(record), flush=True)

    def _handle_assignment_request(self, request: dict) -> None:
        """Handle an assignment request by returning the next FIFO pallet."""
        if not self.queue:
            # No pallets to assign; remain idle
            self.passivate("IDLE")
            return

        # Assign the next pallet in FIFO order
        pallet = self.queue.popleft()
        assignment = {
            "aircraft_id": request["aircraft_id"],
            "pallet_id": pallet["pallet_id"],
            "generation_time": pallet["generation_time"]
        }
        self.output["pallet_claimed_out"].add(assignment)
        self.prepared_pallet = assignment
        self.hold_in("OUTPUT_READY", 0.0)

    def _check_expired_pallets(self) -> None:
        """Check if any pallets in the queue have expired."""
        current_time = get_current_time()
        expired_count = 0
        new_queue = deque()

        for pallet in self.queue:
            if current_time >= pallet["expiration_time"]:
                # Pallet expired
                self.total_expired += 1
                event_payload = {
                    "pallet_id": pallet["pallet_id"],
                    "total_expired": self.total_expired
                }
                record = {
                    "time": current_time,
                    "entity": "queue",
                    "event": "pallet_expired",
                    "payload": event_payload
                }
                print(json.dumps(record), flush=True)
                expired_count += 1
            else:
                new_queue.append(pallet)

        self.queue = new_queue

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return

        # Emit the pallet claimed event via DEVS output port
        # prepared_pallet was set in deltext when handling assignment request
        # The assignment has already been added to the output port in deltext
        pass  # No further action needed in lambdaf()

    def deltint(self):
        self.prepared_pallet = None
        # If there are pallets in queue, we can potentially serve more requests
        # If not, we remain idle
        if not self.queue:
            self.passivate("IDLE")
        else:
            # There are pallets, but we've already handled the assignment
            # and are waiting for the next request
            self.passivate("IDLE")

    def exit(self):
        pass