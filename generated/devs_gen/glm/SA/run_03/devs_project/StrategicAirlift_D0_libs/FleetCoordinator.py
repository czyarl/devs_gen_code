import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class FleetCoordinator(Atomic):
    """Maintains an internal FIFO queue of available aircraft IDs received via the idle_in port."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Input Ports
        self.add_in_port(Port(dict, "idle_in"))
        self.add_in_port(Port(dict, "claim_in"))

        # Output Ports
        self.add_out_port(Port(dict, "request_out"))
        self.add_out_port(Port(dict, "assignment_out"))

        # Internal State
        self.idle_queue: deque[int] = deque()
        self.pending_aircraft_id: int | None = None
        self.prepared_assignment: dict | None = None

    def initialize(self):
        """Initialize internal state and passivate."""
        self.idle_queue = deque()
        self.pending_aircraft_id = None
        self.prepared_assignment = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        """Handle incoming idle notifications and claims."""
        if self.phase == "OUTPUT_READY":
            # If we are about to emit output, preserve remaining time.
            self.continuef(e)
            return

        # Process idle_in inputs
        for msg in self.input["idle_in"].values:
            aircraft_id = msg["aircraft_id"]
            if self.pending_aircraft_id is None:
                # If not waiting for a claim, we can use this immediately
                self.pending_aircraft_id = aircraft_id
                # Schedule immediate output of request
                self.hold_in("OUTPUT_READY", 0.0)
            else:
                # If waiting for a claim, buffer the idle aircraft
                self.idle_queue.append(aircraft_id)

        # Process claim_in inputs
        for msg in self.input["claim_in"].values:
            # Validate aircraft_id matches pending request
            if self.pending_aircraft_id is not None and msg["aircraft_id"] == self.pending_aircraft_id:
                # Valid claim, prepare assignment
                self.prepared_assignment = {
                    "aircraft_id": msg["aircraft_id"],
                    "pallet_id": msg["pallet_id"],
                    "generation_time": msg["generation_time"]
                }
                # Clear pending state
                self.pending_aircraft_id = None
                # Schedule immediate output of assignment
                self.hold_in("ASSIGNMENT_READY", 0.0)
            # If claim doesn't match, ignore it (system integrity implies this shouldn't happen)

    def lambdaf(self):
        """Emit DEVS port outputs based on current phase."""
        if self.phase == "OUTPUT_READY":
            # Send request to LoadingQueue
            if self.pending_aircraft_id is not None:
                self.output["request_out"].add({"aircraft_id": self.pending_aircraft_id})
        
        elif self.phase == "ASSIGNMENT_READY":
            # Send assignment to Aircraft
            if self.prepared_assignment is not None:
                self.output["assignment_out"].add(self.prepared_assignment)
                
                # Write external IO record to stdout
                record = {
                    "time": get_current_time(),
                    "entity": "coordinator",
                    "event": "assignment_created",
                    "payload": {
                        "aircraft_id": self.prepared_assignment["aircraft_id"],
                        "pallet_id": self.prepared_assignment["pallet_id"]
                    }
                }
                print(json.dumps(record), flush=True)

    def deltint(self):
        """Update state after internal transition."""
        if self.phase == "OUTPUT_READY":
            # Request sent. Now wait for claim.
            self.passivate("WAITING_FOR_CLAIM")
        
        elif self.phase == "ASSIGNMENT_READY":
            # Assignment sent. Check queue for next aircraft.
            self.prepared_assignment = None
            
            if self.idle_queue:
                # Dequeue next aircraft and start new cycle
                self.pending_aircraft_id = self.idle_queue.popleft()
                self.hold_in("OUTPUT_READY", 0.0)
            else:
                # No more aircraft, go idle
                self.pending_aircraft_id = None
                self.passivate("IDLE")

    def exit(self):
        """Cleanup."""
        pass