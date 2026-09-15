"""Atomic DEVS model for an Aircraft unit."""

import json
import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class Aircraft(Atomic):
    """Simulates a single aircraft unit."""

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

        # Internal state variables
        self.current_pallet_id = None
        self.current_generation_time = None

        # Ports
        self.add_in_port(Port(dict, "assignment_in"))
        self.add_out_port(Port(dict, "idle_out"))
        self.add_out_port(Port(dict, "delivery_out"))

    def initialize(self):
        """Initialize in IDLE state, immediately emitting idle_out."""
        self.current_pallet_id = None
        self.current_generation_time = None
        # Schedule immediate output for idle status
        self.hold_in("IDLE_OUTPUT", 0.0)

    def deltext(self, e: float):
        """Handle external inputs."""
        if self.phase == "IDLE":
            # Only accept assignment if IDLE
            for assignment in self.input["assignment_in"].values:
                # Check if assignment is for this aircraft
                if assignment.get("aircraft_id") == self.aircraft_id:
                    self.current_pallet_id = assignment.get("pallet_id")
                    self.current_generation_time = assignment.get("generation_time")
                    # Transition to LOAD (0s duration)
                    self.hold_in("LOAD", 0.0)
                    break
        else:
            # Ignore external inputs while busy
            # Preserve remaining time for the current phase
            self.continuef(e)

    def lambdaf(self):
        """Emit outputs based on current phase."""
        now = get_current_time()

        if self.phase == "IDLE_OUTPUT":
            # Report idle status to FleetCoordinator
            self.output["idle_out"].add({"aircraft_id": self.aircraft_id})

        elif self.phase == "LOAD":
            # Emit depart JSONL
            record = {
                "time": now,
                "entity": "aircraft",
                "event": "depart",
                "payload": {
                    "aircraft_id": self.aircraft_id,
                    "pallet_id": self.current_pallet_id,
                },
            }
            print(json.dumps(record), flush=True)

        elif self.phase == "UNLOAD":
            # Send completed delivery info to Destination
            self.output["delivery_out"].add({
                "aircraft_id": self.aircraft_id,
                "pallet_id": self.current_pallet_id,
                "generation_time": self.current_generation_time,
            })

        elif self.phase == "RETURN":
            # Emit return JSONL
            record = {
                "time": now,
                "entity": "aircraft",
                "event": "return",
                "payload": {"aircraft_id": self.aircraft_id},
            }
            print(json.dumps(record), flush=True)

        elif self.phase == "MAINTENANCE":
            # Emit maintenance_start JSONL
            record = {
                "time": now,
                "entity": "aircraft",
                "event": "maintenance_start",
                "payload": {"aircraft_id": self.aircraft_id},
            }
            print(json.dumps(record), flush=True)

        elif self.phase == "MAINTENANCE_END_OUTPUT":
            # Emit maintenance_end JSONL
            record = {
                "time": now,
                "entity": "aircraft",
                "event": "maintenance_end",
                "payload": {"aircraft_id": self.aircraft_id},
            }
            print(json.dumps(record), flush=True)
            
            # Report idle status to FleetCoordinator
            self.output["idle_out"].add({"aircraft_id": self.aircraft_id})

    def deltint(self):
        """Handle internal state transitions."""
        if self.phase == "IDLE_OUTPUT":
            # After announcing idle, wait for assignment
            self.passivate("IDLE")

        elif self.phase == "LOAD":
            # Load is 0s, transition to FLY
            self.hold_in("FLY", self.flight_time)

        elif self.phase == "FLY":
            # Fly complete, transition to UNLOAD
            self.hold_in("UNLOAD", self.unload_time)

        elif self.phase == "UNLOAD":
            # Unload complete, transition to RETURN
            self.hold_in("RETURN", self.return_time)

        elif self.phase == "RETURN":
            # Return complete, transition to MAINTENANCE
            self.hold_in("MAINTENANCE", self.maintenance_time)

        elif self.phase == "MAINTENANCE":
            # Maintenance complete, prepare to emit end event and idle
            self.hold_in("MAINTENANCE_END_OUTPUT", 0.0)

        elif self.phase == "MAINTENANCE_END_OUTPUT":
            # Clear payload and go to IDLE
            self.current_pallet_id = None
            self.current_generation_time = None
            self.passivate("IDLE")

    def exit(self):
        """Cleanup method."""
        pass