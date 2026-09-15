"""Atomic DEVS model representing a single aircraft in the airfreight logistics system."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Aircraft(Atomic):
    """Represents a single aircraft with a stable ID performing cyclic transport operations."""

    def __init__(self, name: str, parent: Coupled | None, aircraft_id: int, flight_time: float,
                 unload_time: float, return_time: float, maintenance_time: float):
        super().__init__(name)
        self.parent = parent
        self.aircraft_id = aircraft_id
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time

        # DEVS ports
        self.add_in_port(Port(dict, "assignment_in"))
        self.add_out_port(Port(dict, "aircraft_idle_out"))
        self.add_out_port(Port(dict, "depart_out"))
        self.add_out_port(Port(dict, "return_out"))
        self.add_out_port(Port(dict, "maintenance_start_out"))
        self.add_out_port(Port(dict, "maintenance_end_out"))

        # Internal state
        self.current_phase = "IDLE"
        self.assigned_pallet = None
        self.assignment_time = None

    def initialize(self):
        # Aircraft starts idle at t=0 and reports availability immediately
        self.hold_in("IDLE", 0.0)

    def deltext(self, e):
        if self.current_phase == "IDLE":
            # Check for assignment
            for assignment in self.input["assignment_in"].values:
                if assignment["aircraft_id"] == self.aircraft_id:
                    self.assigned_pallet = assignment
                    self.assignment_time = get_current_time()
                    # Start loading (0s)
                    self.hold_in("LOADING", 0.0)
                    return
            # No valid assignment, remain idle
            self.passivate("IDLE")
        elif self.current_phase == "LOADING":
            # This is a zero-delay transition, handled in lambdaf
            self.continuef(e)
        elif self.current_phase == "FLYING":
            self.continuef(e)
        elif self.current_phase == "UNLOADING":
            self.continuef(e)
        elif self.current_phase == "RETURNING":
            self.continuef(e)
        elif self.current_phase == "MAINTENANCE":
            self.continuef(e)
        else:
            self.passivate("IDLE")

    def lambdaf(self):
        now = get_current_time()
        if self.current_phase == "IDLE":
            # Report availability
            self.output["aircraft_idle_out"].add({"aircraft_id": self.aircraft_id})
        elif self.current_phase == "LOADING":
            # Emit depart event
            self.output["depart_out"].add({
                "aircraft_id": self.aircraft_id,
                "pallet_id": self.assigned_pallet["pallet_id"]
            })
            # Schedule flight
            self.hold_in("FLYING", self.flight_time)
        elif self.current_phase == "FLYING":
            # Flight complete, start unloading
            self.hold_in("UNLOADING", self.unload_time)
        elif self.current_phase == "UNLOADING":
            # Emit pallet delivered event to destination
            delivery_time = get_current_time()
            latency = delivery_time - self.assigned_pallet["generation_time"]
            # Note: destination receives this through a coupling, so no output port here
            # But we log it for the external IO requirement
            print(json.dumps({
                "time": delivery_time,
                "entity": "destination",
                "event": "pallet_delivered",
                "payload": {
                    "pallet_id": self.assigned_pallet["pallet_id"],
                    "aircraft_id": self.aircraft_id,
                    "latency": latency
                }
            }), flush=True)
            # Schedule return
            self.hold_in("RETURNING", self.return_time)
        elif self.current_phase == "RETURNING":
            # Emit return event
            self.output["return_out"].add({"aircraft_id": self.aircraft_id})
            # Schedule maintenance start
            self.hold_in("MAINTENANCE", self.maintenance_time)
        elif self.current_phase == "MAINTENANCE":
            # Emit maintenance end event
            self.output["maintenance_end_out"].add({"aircraft_id": self.aircraft_id})
            # Return to idle
            self.hold_in("IDLE", 0.0)

    def deltint(self):
        now = get_current_time()
        if self.current_phase == "LOADING":
            self.current_phase = "FLYING"
        elif self.current_phase == "FLYING":
            self.current_phase = "UNLOADING"
        elif self.current_phase == "UNLOADING":
            self.current_phase = "RETURNING"
        elif self.current_phase == "RETURNING":
            self.current_phase = "MAINTENANCE"
        elif self.current_phase == "MAINTENANCE":
            self.current_phase = "IDLE"
            self.assigned_pallet = None
            self.assignment_time = None
        else:
            self.passivate("IDLE")

    def exit(self):
        pass