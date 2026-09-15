"""Atomic DEVS model: LoadingQueue."""

import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class LoadingQueue(Atomic):
    """Maintain an internal FIFO buffer of incoming pallets and a counter for total expired pallets."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Input Ports
        self.add_in_port(Port(dict, "pallet_in"))
        self.add_in_port(Port(dict, "claim_in"))
        
        # Output Ports
        self.add_out_port(Port(dict, "pallet_available"))
        self.add_out_port(Port(dict, "claimed_out"))
        
        # Internal State
        self.queue: deque = deque()
        self.total_expired: int = 0
        self.claim_payload: dict | None = None

    def initialize(self):
        self.queue = deque()
        self.total_expired = 0
        self.claim_payload = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        current_time = get_current_time()
        
        # Process incoming pallets
        for pallet in self.input["pallet_in"].values:
            # Append to buffer
            self.queue.append(dict(pallet))
            
            # Write 'pallet_queued' JSONL record
            record = {
                "time": current_time,
                "entity": "queue",
                "event": "pallet_queued",
                "payload": {
                    "pallet_id": pallet["pallet_id"],
                    "queue_size": len(self.queue)
                }
            }
            print(json.dumps(record), flush=True)
            
            # If buffer transitioned from empty to non-empty, schedule signal
            if len(self.queue) == 1:
                # We schedule an output immediately to signal availability
                # Note: We don't change sigma here yet, deltint will handle the rescheduling
                # based on the new head. However, to emit the signal, we need a phase.
                # We will use a specific phase to emit the signal then calculate sigma.
                self.hold_in("SIGNAL_AVAILABLE", 0.0)

        # Process claims
        for claim in self.input["claim_in"].values:
            if self.queue:
                # Remove head pallet
                head_pallet = self.queue.popleft()
                
                # Merge payload
                self.claim_payload = {
                    "aircraft_id": claim["aircraft_id"],
                    "pallet_id": head_pallet["pallet_id"],
                    "generation_time": head_pallet["generation_time"]
                }
                
                # Schedule output
                self.hold_in("CLAIM_OUTPUT", 0.0)
            else:
                # If queue is empty, ignore claim or passivate? 
                # Contract says "if the buffer is not empty". If empty, do nothing regarding the claim.
                pass

        # If we are in an active phase (like waiting for expiration), we must continue the phase
        # unless a new event (pallet or claim) took precedence.
        # The logic above sets hold_in for new events. If no new events occurred, we continue.
        if self.phase == "IDLE":
            # If we were idle and received nothing, stay idle.
            # If we received a pallet, we are now in SIGNAL_AVAILABLE.
            # If we received a claim (and queue was not empty), we are in CLAIM_OUTPUT.
            pass
        elif self.phase == "WAITING_FOR_EXPIRATION":
            # If we were waiting for expiration, we need to check if the head changed.
            # If the head was claimed, the queue might be empty or have a new head.
            # If a new pallet arrived, the head might have changed (if queue was empty).
            
            # Recalculate sigma based on the new head.
            if self.queue:
                head = self.queue[0]
                new_deadline = head["expiration_time"]
                time_remaining = new_deadline - current_time
                
                # If the deadline is in the past (shouldn't happen with correct logic, but safety check)
                if time_remaining <= 0:
                    # Should expire immediately
                    self.hold_in("EXPIRE_NOW", 0.0)
                else:
                    self.continuef(e) # This preserves the phase but subtracts e.
                    # However, if the head changed, the deadline might have changed.
                    # If the head changed, we need to reset sigma to the new deadline.
                    # But `continuef` just subtracts e. We need to explicitly set sigma if head changed.
                    # Actually, if we are in WAITING_FOR_EXPIRATION, we are waiting for the *current* head.
                    # If the head is removed (claimed), we need to reschedule for the next.
                    # If a new pallet is added to an empty queue, we set SIGNAL_AVAILABLE.
                    
                    # Let's refine the logic:
                    # If we are in WAITING_FOR_EXPIRATION, it means we had a head.
                    # If we received a claim and removed the head, we must recalculate for the new head.
                    # If we received a pallet but queue wasn't empty, head didn't change, just continue.
                    # If we received a pallet and queue was empty, we went to SIGNAL_AVAILABLE.
                    
                    # The tricky part is: `deltext` is called with `e` elapsed.
                    # If we are in WAITING_FOR_EXPIRATION, `self.sigma` was time to old head.
                    # If we claimed the head, we need to set `sigma` to time to new head.
                    # If we didn't claim the head, we just continue.
                    
                    # How do we know if we claimed the head in this `deltext`?
                    # We check if we transitioned to CLAIM_OUTPUT.
                    if self.phase != "CLAIM_OUTPUT" and self.phase != "SIGNAL_AVAILABLE":
                        self.continuef(e)
            else:
                # Queue became empty (e.g. last pallet claimed)
                self.passivate("IDLE")
        elif self.phase == "SIGNAL_AVAILABLE":
            # Already scheduled output
            pass
        elif self.phase == "CLAIM_OUTPUT":
            # Already scheduled output
            pass

    def deltint(self):
        current_time = get_current_time()
        
        if self.phase == "SIGNAL_AVAILABLE":
            # Signal emitted, now calculate timer for the head
            if self.queue:
                head = self.queue[0]
                deadline = head["expiration_time"]
                sigma = deadline - current_time
                if sigma <= 0:
                    # Should handle immediately, but usually scheduling 0.0 handles it.
                    # However, to be safe:
                    self.hold_in("EXPIRE_NOW", 0.0)
                else:
                    self.hold_in("WAITING_FOR_EXPIRATION", sigma)
            else:
                self.passivate("IDLE")
                
        elif self.phase == "CLAIM_OUTPUT":
            # Claim emitted, calculate timer for new head
            self.claim_payload = None
            if self.queue:
                head = self.queue[0]
                deadline = head["expiration_time"]
                sigma = deadline - current_time
                if sigma <= 0:
                    self.hold_in("EXPIRE_NOW", 0.0)
                else:
                    self.hold_in("WAITING_FOR_EXPIRATION", sigma)
            else:
                self.passivate("IDLE")
                
        elif self.phase == "EXPIRE_NOW" or self.phase == "WAITING_FOR_EXPIRATION":
            # Internal transition for expiration
            if self.queue:
                # Remove head
                head = self.queue.popleft()
                
                # Write 'pallet_expired' record
                self.total_expired += 1
                record = {
                    "time": current_time,
                    "entity": "queue",
                    "event": "pallet_expired",
                    "payload": {
                        "pallet_id": head["pallet_id"],
                        "total_expired": self.total_expired
                    }
                }
                print(json.dumps(record), flush=True)
                
                # Reschedule for next pallet
                if self.queue:
                    next_head = self.queue[0]
                    next_deadline = next_head["expiration_time"]
                    sigma = next_deadline - current_time
                    if sigma <= 0:
                        # If next one is also expired (possible if multiple arrived at once or logic gap)
                        self.hold_in("EXPIRE_NOW", 0.0)
                    else:
                        self.hold_in("WAITING_FOR_EXPIRATION", sigma)
                else:
                    self.passivate("IDLE")
            else:
                # Should not happen if we were waiting, but safety passivate
                self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "SIGNAL_AVAILABLE":
            self.output["pallet_available"].add({})
        elif self.phase == "CLAIM_OUTPUT":
            if self.claim_payload:
                self.output["claimed_out"].add(self.claim_payload)

    def exit(self):
        pass