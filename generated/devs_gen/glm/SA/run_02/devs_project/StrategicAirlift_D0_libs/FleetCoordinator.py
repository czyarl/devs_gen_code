import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class FleetCoordinator(Atomic):
    """Track idle aircraft and queued pallets. When both are available, send a claim request."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Input Ports
        self.add_in_port(Port(dict, "idle_in"))
        self.add_in_port(Port(dict, "pallet_available"))
        self.add_in_port(Port(dict, "claimed_in"))
        
        # Output Ports
        self.add_out_port(Port(dict, "claim_out"))
        self.add_out_port(Port(dict, "assignment_out"))
        
        # Internal State
        self.idle_aircraft = deque()
        self.pallets_available = False
        self.pending_claim_aircraft_id = None
        self.pending_assignment = None

    def initialize(self):
        self.idle_aircraft = deque()
        self.pallets_available = False
        self.pending_claim_aircraft_id = None
        self.pending_assignment = None
        self.passivate("IDLE")

    def deltext(self, e):
        # If we are in the middle of an output sequence, preserve remaining time
        if self.phase == "OUTPUT_READY":
            self.continuef(e)
            return

        # Process idle aircraft notifications
        for msg in self.input["idle_in"].values:
            aircraft_id = int(msg["aircraft_id"])
            # Avoid duplicates if an aircraft sends multiple signals (though logic implies single signal)
            if aircraft_id not in self.idle_aircraft:
                self.idle_aircraft.append(aircraft_id)

        # Process pallet availability notifications
        # The port sends empty dicts {} to signal availability
        if not self.input["pallet_available"].empty():
            self.pallets_available = True

        # Process claimed pallets from Loading Queue
        for msg in self.input["claimed_in"].values:
            # We expect the claimed pallet to match the aircraft we just offered
            # Store it to emit the assignment immediately
            self.pending_assignment = {
                "aircraft_id": int(msg["aircraft_id"]),
                "pallet_id": int(msg["pallet_id"]),
                "generation_time": float(msg["generation_time"])
            }
            # Schedule immediate output for the assignment
            self.hold_in("OUTPUT_READY", 0.0)
            return

        # Check if we can initiate a new claim
        # We can only claim if we have an idle aircraft AND we know pallets are available
        if self.idle_aircraft and self.pallets_available:
            self.pending_claim_aircraft_id = self.idle_aircraft.popleft()
            self.hold_in("CLAIM_READY", 0.0)
        else:
            self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "CLAIM_READY":
            # Send claim request to Loading Queue
            self.output["claim_out"].add({"aircraft_id": self.pending_claim_aircraft_id})
        
        elif self.phase == "OUTPUT_READY":
            # Emit the assignment to the Aircraft
            if self.pending_assignment:
                self.output["assignment_out"].add(self.pending_assignment)
                
                # External IO: Write 'assignment_created' record to stdout
                print(json.dumps({
                    "time": get_current_time(),
                    "entity": "coordinator",
                    "event": "assignment_created",
                    "payload": {
                        "aircraft_id": self.pending_assignment["aircraft_id"],
                        "pallet_id": self.pending_assignment["pallet_id"]
                    }
                }), flush=True)

    def deltint(self):
        if self.phase == "CLAIM_READY":
            # After sending the claim, we wait for the 'claimed_in' response.
            # We passivate until the response arrives.
            self.pending_claim_aircraft_id = None
            self.passivate("WAITING_FOR_CLAIM")
            
        elif self.phase == "OUTPUT_READY":
            # Assignment sent. Clear state.
            self.pending_assignment = None
            
            # Check if we can start another cycle immediately
            if self.idle_aircraft and self.pallets_available:
                self.pending_claim_aircraft_id = self.idle_aircraft.popleft()
                self.hold_in("CLAIM_READY", 0.0)
            else:
                self.passivate("IDLE")

    def exit(self):
        pass