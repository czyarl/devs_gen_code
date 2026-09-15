from xdevs.models import Atomic, Coupled, Port
import json
import sys

from devs_project.devs_utils.devs_context import get_current_time


class Aircraft(Atomic):
    """Simulates a single aircraft instance executing a cyclic logistics lifecycle."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        aircraft_id: int,
        flight_time: float,
        unload_time: float,
        return_time: float,
        maintenance_time: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.aircraft_id = aircraft_id
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time

        # Internal state
        self.current_pallet_id = None
        self.current_generation_time = None

        # Ports
        self.add_in_port(Port(dict, "assignment_in"))
        self.add_out_port(Port(dict, "idle_out"))
        self.add_out_port(Port(dict, "delivery_out"))

    def initialize(self):
        # Initialize in IDLE state and immediately broadcast availability
        self.current_pallet_id = None
        self.current_generation_time = None
        self.hold_in("IDLE", 0.0)

    def deltext(self, e: float):
        # While in non-idle states (FLY, UNLOAD, RETURN, MAINTENANCE), ignore incoming assignments.
        if self.phase != "IDLE":
            # Preserve remaining time for the current active phase
            self.continuef(e)
            return

        # In IDLE state, check for assignments
        for payload in self.input["assignment_in"].values:
            # Validate that the aircraft_id matches its own ID
            if payload.get("aircraft_id") == self.aircraft_id:
                self.current_pallet_id = payload.get("pallet_id")
                self.current_generation_time = payload.get("generation_time")
                
                # Transition from IDLE to LOAD. 
                # The LOAD phase has zero duration, triggering an immediate depart record.
                self.hold_in("LOAD", 0.0)
                break

    def lambdaf(self):
        now = get_current_time()
        
        # Emit idle_out at t=0 (initialization) and after maintenance
        if self.phase == "IDLE":
            self.output["idle_out"].add({"aircraft_id": self.aircraft_id})

        # Trigger 'depart' JSONL record to stdout at LOAD phase
        elif self.phase == "LOAD":
            record = {
                "time": now,
                "entity": "aircraft",
                "event": "depart",
                "payload": {
                    "aircraft_id": self.aircraft_id,
                    "pallet_id": self.current_pallet_id
                }
            }
            print(json.dumps(record), flush=True)

        # Send delivery_out payload to Destination when UNLOAD completes
        elif self.phase == "UNLOAD":
            self.output["delivery_out"].add({
                "aircraft_id": self.aircraft_id,
                "pallet_id": self.current_pallet_id,
                "generation_time": self.current_generation_time
            })

        # Write 'return' JSONL record to stdout when RETURN completes
        elif self.phase == "RETURN":
            record = {
                "time": now,
                "entity": "aircraft",
                "event": "return",
                "payload": {"aircraft_id": self.aircraft_id}
            }
            print(json.dumps(record), flush=True)

        # Write 'maintenance_end' JSONL record to stdout when MAINTENANCE completes
        elif self.phase == "MAINTENANCE":
            record = {
                "time": now,
                "entity": "aircraft",
                "event": "maintenance_end",
                "payload": {"aircraft_id": self.aircraft_id}
            }
            print(json.dumps(record), flush=True)

    def deltint(self):
        # State transition logic based on current phase
        
        if self.phase == "IDLE":
            # After broadcasting idle, wait passively for assignment
            self.passivate("IDLE")

        elif self.phase == "LOAD":
            # Load is 0s, transition to FLY
            self.hold_in("FLY", self.flight_time)

        elif self.phase == "FLY":
            # Flight done, transition to UNLOAD
            self.hold_in("UNLOAD", self.unload_time)

        elif self.phase == "UNLOAD":
            # Unload done, transition to RETURN
            self.hold_in("RETURN", self.return_time)

        elif self.phase == "RETURN":
            # Return done, transition to MAINTENANCE
            # Write maintenance_start immediately upon entering maintenance
            now = get_current_time()
            record = {
                "time": now,
                "entity": "aircraft",
                "event": "maintenance_start",
                "payload": {"aircraft_id": self.aircraft_id}
            }
            print(json.dumps(record), flush=True)
            
            self.hold_in("MAINTENANCE", self.maintenance_time)

        elif self.phase == "MAINTENANCE":
            # Maintenance done, clear current job and return to IDLE
            self.current_pallet_id = None
            self.current_generation_time = None
            self.hold_in("IDLE", 0.0)

    def exit(self):
        pass