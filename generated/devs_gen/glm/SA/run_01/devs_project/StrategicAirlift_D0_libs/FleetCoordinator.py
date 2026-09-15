import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class FleetCoordinator(Atomic):
    """Matches idle aircraft with available pallets."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Input Ports
        self.add_in_port(Port(dict, "aircraft_idle_in"))
        self.add_in_port(Port(dict, "pallet_claimed_in"))
        self.add_in_port(Port(dict, "pallet_available_in"))

        # Output Ports
        self.add_out_port(Port(dict, "queue_request_out"))
        self.add_out_port(Port(dict, "assignment_out"))

        # Internal State
        self.idle_aircraft_buffer: deque[int] = deque()
        self.pallets_available: bool = False
        self.pending_aircraft_id: int | None = None
        self.pending_pallet_id: int | None = None
        self.pending_generation_time: float | None = None

    def initialize(self):
        self.idle_aircraft_buffer = deque()
        self.pallets_available = False
        self.pending_aircraft_id = None
        self.pending_pallet_id = None
        self.pending_generation_time = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        # If we are in the middle of outputting, we continue the phase
        if self.phase == "OUTPUT_ASSIGNMENT":
            self.continuef(e)
            return

        # Process incoming idle aircraft
        for msg in self.input["aircraft_idle_in"].values:
            aircraft_id = int(msg["aircraft_id"])
            self.idle_aircraft_buffer.append(aircraft_id)

        # Process notification that pallets are available
        for _ in self.input["pallet_available_in"].values:
            self.pallets_available = True

        # Process claimed pallet from LoadingQueue
        for msg in self.input["pallet_claimed_in"].values:
            aircraft_id = int(msg["aircraft_id"])
            pallet_id = int(msg["pallet_id"])
            generation_time = float(msg["generation_time"])
            queue_remaining_count = int(msg["queue_remaining_count"])

            # Store assignment details
            self.pending_aircraft_id = aircraft_id
            self.pending_pallet_id = pallet_id
            self.pending_generation_time = generation_time

            # Update queue availability flag based on remaining count
            self.pallets_available = (queue_remaining_count > 0)

            # Schedule immediate output for the assignment
            self.hold_in("OUTPUT_ASSIGNMENT", 0.0)
            return

        # If we received inputs but didn't get a claimed pallet (which forces output),
        # check if we can start a new request cycle.
        if self.pallets_available and self.idle_aircraft_buffer:
            # We have both resources, schedule a request to the queue
            self.hold_in("REQUESTING", 0.0)
        else:
            # Wait for more resources
            self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "REQUESTING":
            # Send a request to the LoadingQueue for the first idle aircraft
            if self.idle_aircraft_buffer:
                aircraft_id = self.idle_aircraft_buffer[0]
                self.output["queue_request_out"].add({"aircraft_id": aircraft_id})
        
        elif self.phase == "OUTPUT_ASSIGNMENT":
            # Broadcast the assignment to the fleet
            if self.pending_aircraft_id is not None:
                payload = {
                    "aircraft_id": self.pending_aircraft_id,
                    "pallet_id": self.pending_pallet_id,
                    "generation_time": self.pending_generation_time
                }
                self.output["assignment_out"].add(payload)

                # Write JSONL record to stdout
                record = {
                    "time": get_current_time(),
                    "entity": "coordinator",
                    "event": "assignment_created",
                    "payload": {
                        "aircraft_id": self.pending_aircraft_id,
                        "pallet_id": self.pending_pallet_id
                    }
                }
                print(json.dumps(record), flush=True)

    def deltint(self):
        if self.phase == "REQUESTING":
            # After sending a request, we wait for the response (pallet_claimed_in)
            # We passivate because we are waiting for external input
            self.passivate("WAITING_RESPONSE")
        
        elif self.phase == "OUTPUT_ASSIGNMENT":
            # Clear the pending assignment state
            self.pending_aircraft_id = None
            self.pending_pallet_id = None
            self.pending_generation_time = None

            # Check if we can immediately process another match
            # The logic in deltext handles the check based on the updated state
            if self.pallets_available and self.idle_aircraft_buffer:
                self.hold_in("REQUESTING", 0.0)
            else:
                self.passivate("IDLE")

    def exit(self):
        pass