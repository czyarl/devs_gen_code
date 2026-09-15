import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class LoadingQueue(Atomic):
    """Maintains a FIFO queue of pallets, actively monitoring deadlines to enforce expiration."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Input Ports
        self.add_in_port(Port(dict, "pallet_in"))
        self.add_in_port(Port(dict, "request_in"))

        # Output Ports
        self.add_out_port(Port(dict, "claim_out"))

        # State variables
        self.queue: deque[dict] = deque()
        self.total_expired: int = 0
        self.prepared_claim: dict | None = None

    def initialize(self):
        self.queue = deque()
        self.total_expired = 0
        self.prepared_claim = None
        # Startup initializes an empty queue and sets sigma to infinity.
        self.passivate("IDLE")

    def _update_sigma(self):
        """Updates sigma based on the earliest expiring pallet in the queue."""
        if not self.queue:
            self.passivate("IDLE")
        else:
            # The queue is FIFO. Since generation_time is non-decreasing and expiration_time
            # is generation_time + constant, the head of the queue is always the earliest expiring.
            head_pallet = self.queue[0]
            earliest_expiration = head_pallet["expiration_time"]
            current_time = get_current_time()
            time_to_expire = earliest_expiration - current_time
            
            if time_to_expire < 0:
                # Should have expired already, trigger immediately
                self.hold_in("ACTIVE", 0.0)
            else:
                self.hold_in("ACTIVE", time_to_expire)

    def deltext(self, e: float):
        # If we are in the middle of an output action, we just continue the phase
        if self.phase == "OUTPUT_READY":
            self.continuef(e)
            return

        current_time = get_current_time()
        
        # Handle incoming pallets
        for pallet in self.input["pallet_in"].values:
            # Structure: {'pallet_id': int, 'generation_time': float, 'expiration_time': float}
            new_pallet = dict(pallet)
            self.queue.append(new_pallet)
            
            # Write 'pallet_queued' JSONL record
            record = {
                "time": current_time,
                "entity": "queue",
                "event": "pallet_queued",
                "payload": {
                    "pallet_id": new_pallet["pallet_id"],
                    "queue_size": len(self.queue)
                }
            }
            print(json.dumps(record), flush=True)

        # Handle incoming requests
        # We process at most one request per external transition to match the singular output capability
        # implied by the contract and typical atomic DEVS patterns.
        request_processed = False
        for request in self.input["request_in"].values:
            if self.queue:
                # Structure: {'aircraft_id': int}
                head_pallet = self.queue.popleft()
                
                # Prepare claim payload
                self.prepared_claim = {
                    "aircraft_id": request["aircraft_id"],
                    "pallet_id": head_pallet["pallet_id"],
                    "generation_time": head_pallet["generation_time"]
                }
                
                # Schedule output
                self.hold_in("OUTPUT_READY", 0.0)
                request_processed = True
                break 
        
        if not request_processed:
            # If no request was processed, update sigma based on the queue state (which might have new pallets)
            self._update_sigma()
        # If request processed, we are in OUTPUT_READY, deltint will handle the next state.

    def lambdaf(self):
        if self.phase == "OUTPUT_READY" and self.prepared_claim is not None:
            self.output["claim_out"].add(self.prepared_claim)

    def deltint(self):
        if self.phase == "OUTPUT_READY":
            # We just finished outputting a claim.
            # The pallet was already removed from the queue in `deltext`.
            self.prepared_claim = None
            # Update sigma for the next expiration
            self._update_sigma()
        
        elif self.phase == "ACTIVE":
            # Internal transition triggered by sigma reaching 0 (expiration check)
            if self.queue:
                head_pallet = self.queue[0]
                current_time = get_current_time()
                
                # Check if expiration time is less than or equal to current time
                if head_pallet["expiration_time"] <= current_time:
                    # It is expired. Discard it.
                    expired_pallet = self.queue.popleft()
                    self.total_expired += 1
                    
                    # Write 'pallet_expired' JSONL record
                    record = {
                        "time": current_time,
                        "entity": "queue",
                        "event": "pallet_expired",
                        "payload": {
                            "pallet_id": expired_pallet["pallet_id"],
                            "total_expired": self.total_expired
                        }
                    }
                    print(json.dumps(record), flush=True)
                    
                    # Recalculate sigma for the next expiration
                    self._update_sigma()
                else:
                    # Head is not expired, but sigma was 0. This can happen if time advanced
                    # and we missed an update, or if the head was swapped.
                    # Recalculate to be safe.
                    self._update_sigma()
            else:
                # Queue is empty
                self.passivate("IDLE")

    def exit(self):
        pass