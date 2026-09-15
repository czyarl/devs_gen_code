import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class LoadingQueue(Atomic):
    """Maintain an internal FIFO buffer of incoming pallets and actively monitor deadlines."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Input Ports
        self.add_in_port(Port(dict, "pallet_in"))
        self.add_in_port(Port(dict, "request_in"))
        
        # Output Ports
        self.add_out_port(Port(dict, "pallet_claimed_out"))
        self.add_out_port(Port(dict, "pallet_available_out"))
        
        # Internal State
        self.queue: deque = deque()
        self.total_expired: int = 0
        self.next_deadline: float = float('inf')
        
        # State for output emission
        self.pallet_to_claim: dict | None = None
        self.pallet_available_signal: bool = False
        self.pallet_to_expire: dict | None = None

    def initialize(self):
        self.queue.clear()
        self.total_expired = 0
        self.next_deadline = float('inf')
        self.pallet_to_claim = None
        self.pallet_available_signal = False
        self.pallet_to_expire = None
        self.passivate("IDLE")

    def _update_timer(self):
        """Update internal timer based on the head of the queue."""
        if self.queue:
            # The head of the FIFO queue has the earliest deadline because pallets are generated
            # sequentially and deadlines are generation_time + constant.
            # However, to be robust, we check the head.
            head_pallet = self.queue[0]
            self.next_deadline = head_pallet['deadline']
        else:
            self.next_deadline = float('inf')

    def deltext(self, e: float):
        current_time = get_current_time()
        
        # If we are in the middle of processing an output (zero-delay phase), 
        # we must continue that phase and ignore new input for this instant to avoid 
        # breaking the output contract, or handle it if the logic allows.
        # Standard DEVS: deltcon handles simultaneous events. 
        # If we are in OUTPUT_READY, we continue the phase.
        if self.phase == "OUTPUT_READY":
            self.continuef(e)
            return

        # Process incoming pallets
        for pallet in self.input["pallet_in"].values:
            # Append to queue
            self.queue.append(dict(pallet))
            
            # External IO: pallet_queued
            print(json.dumps({
                "time": current_time,
                "entity": "queue",
                "event": "pallet_queued",
                "payload": {
                    "pallet_id": pallet["pallet_id"],
                    "queue_size": len(self.queue)
                }
            }), flush=True)
            
            # If queue was empty, signal availability
            if len(self.queue) == 1:
                self.pallet_available_signal = True

        # Process incoming requests
        # Note: We only process requests if we are not currently processing an expiration.
        # If a request arrives at the same time as an expiration, standard DEVS deltcon 
        # or the specific order of operations matters. 
        # Here, we handle requests. If we have a pallet, we prepare the claim.
        # If multiple requests arrive, we can only serve one (the head of the queue).
        # The contract says "remove the head pallet... emit it".
        # Since this is an atomic model processing a bag of events, we iterate.
        # However, we can only dispatch one pallet per internal transition cycle effectively
        # unless we loop. The contract implies immediate response.
        # We will take the first request if queue is not empty.
        if self.queue and not self.input["request_in"].empty:
            request = self.input["request_in"].get()
            head_pallet = self.queue.popleft()
            
            self.pallet_to_claim = {
                "aircraft_id": request["aircraft_id"],
                "pallet_id": head_pallet["pallet_id"],
                "generation_time": head_pallet["generation_time"],
                "queue_remaining_count": len(self.queue)
            }
            
            # After removing a pallet, we must update the timer
            self._update_timer()

        # Determine next phase
        # Priority: Expiration > Output Emission
        # If we have something to emit (claim or available), we schedule output.
        # If we have an expiration pending, we schedule expiration.
        # If we have both, expiration happens first (time advance).
        
        # Check for expiration
        if self.queue and self.next_deadline <= current_time:
            # The head is expiring now.
            self.pallet_to_expire = self.queue[0]
            self.hold_in("EXPIRING", 0.0)
        elif self.pallet_to_claim or self.pallet_available_signal:
            self.hold_in("OUTPUT_READY", 0.0)
        elif self.queue:
            # Wait for next deadline
            self.hold_in("WAITING", self.next_deadline - current_time)
        else:
            self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "OUTPUT_READY":
            if self.pallet_to_claim:
                self.output["pallet_claimed_out"].add(self.pallet_to_claim)
            
            if self.pallet_available_signal:
                self.output["pallet_available_out"].add({})
        
        # EXPIRING phase does not emit DEVS output, it just handles internal logic in deltint
        # or could emit if required. Contract says "write a pallet_expired JSONL record", 
        # but doesn't specify a DEVS output port for expiration.
        # So no DEVS output in EXPIRING phase.

    def deltint(self):
        current_time = get_current_time()
        
        if self.phase == "OUTPUT_READY":
            # Reset flags
            self.pallet_to_claim = None
            self.pallet_available_signal = False
            
            # Check if we need to expire immediately after output
            # (e.g. if we just removed a pallet and the next one is already expired)
            if self.queue and self.next_deadline <= current_time:
                self.pallet_to_expire = self.queue[0]
                self.hold_in("EXPIRING", 0.0)
            elif self.queue:
                self.hold_in("WAITING", self.next_deadline - current_time)
            else:
                self.passivate("IDLE")
                
        elif self.phase == "EXPIRING":
            # Process expiration
            # We might have multiple expired if time jumped or if we loop
            # The contract says: "repeat the inspection for the new head"
            # We handle one per internal transition to allow interrupts, 
            # but since sigma is 0, we will loop back immediately if still expired.
            
            if self.queue:
                head_pallet = self.queue.popleft()
                self.total_expired += 1
                
                # External IO: pallet_expired
                print(json.dumps({
                    "time": current_time,
                    "entity": "queue",
                    "event": "pallet_expired",
                    "payload": {
                        "pallet_id": head_pallet["pallet_id"],
                        "total_expired": self.total_expired
                    }
                }), flush=True)
                
                # Update timer for the new head
                self._update_timer()
                
                # Check if the new head is also expired
                if self.queue and self.next_deadline <= current_time:
                    # Continue expiring
                    self.hold_in("EXPIRING", 0.0)
                elif self.queue:
                    # Wait for next deadline
                    self.hold_in("WAITING", self.next_deadline - current_time)
                else:
                    # Queue empty
                    self.passivate("IDLE")
            else:
                # Should not happen if logic is correct, but safe fallback
                self.passivate("IDLE")

    def exit(self):
        pass