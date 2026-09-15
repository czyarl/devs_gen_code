"""LoadingQueue DEVS model implementing FIFO pallet queuing with expiration."""

import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class LoadingQueue(Atomic):
    """Holds incoming pallets and monitors their deadlines."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "pallet_in"))
        self.add_in_port(Port(dict, "assignment_request_in"))
        self.add_out_port(Port(dict, "pallet_claimed_out"))
        self.queue = deque()
        self.total_expired = 0
        self.prepared_assignment = None

    def initialize(self):
        self.queue = deque()
        self.total_expired = 0
        self.prepared_assignment = None
        self.passivate("IDLE")

    def _check_expirations(self) -> None:
        current_time = get_current_time()
        expired_count = 0
        while self.queue and self.queue[0]["expiration_time"] <= current_time:
            expired_pallet = self.queue.popleft()
            self.total_expired += 1
            expired_count += 1
            print(json.dumps({
                "time": current_time,
                "entity": "queue",
                "event": "pallet_expired",
                "payload": {
                    "pallet_id": expired_pallet["pallet_id"],
                    "total_expired": self.total_expired
                }
            }), flush=True)
        if expired_count > 0:
            # If we expired pallets, we need to recheck for assignments
            self._prepare_assignment_if_possible()

    def _prepare_assignment_if_possible(self) -> None:
        if not self.queue:
            self.passivate("IDLE")
            return

        self.prepared_assignment = self.queue[0]
        self.hold_in("OUTPUT_READY", 0.0)

    def deltext(self, e):
        if self.phase == "OUTPUT_READY":
            self.continuef(e)
            return

        # Process incoming pallets
        for pallet in self.input["pallet_in"].values:
            self.queue.append(dict(pallet))
            print(json.dumps({
                "time": get_current_time(),
                "entity": "queue",
                "event": "pallet_queued",
                "payload": {
                    "pallet_id": pallet["pallet_id"],
                    "queue_size": len(self.queue)
                }
            }), flush=True)

        # Process assignment requests
        for request in self.input["assignment_request_in"].values:
            # We don't need to do anything with the request itself,
            # just check if we can assign
            pass

        # Check for expirations and prepare assignment if possible
        self._check_expirations()
        if self.phase != "OUTPUT_READY":
            self._prepare_assignment_if_possible()

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return

        # Emit the assignment
        assignment = dict(self.prepared_assignment)
        self.output["pallet_claimed_out"].add(assignment)

        # Remove the assigned pallet from the queue
        self.queue.popleft()

        # Check for more assignments
        self._prepare_assignment_if_possible()

    def deltint(self):
        self.prepared_assignment = None
        # Check for expirations after internal transition
        self._check_expirations()
        # If we still have assignments ready, prepare one
        if self.phase == "OUTPUT_READY":
            self._prepare_assignment_if_possible()

    def exit(self):
        pass