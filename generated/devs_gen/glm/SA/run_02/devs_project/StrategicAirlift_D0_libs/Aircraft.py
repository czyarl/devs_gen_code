from xdevs.models import Atomic, Coupled, Port
import json
import sys
from devs_project.devs_utils.devs_context import get_current_time

class Aircraft(Atomic):
    """
    Runtime aircraft blueprint.
    Start in IDLE state and immediately emit `idle_out` containing `aircraft_id`.
    While IDLE, accept incoming assignments on `assignment_in` only if the payload's `aircraft_id` matches this instance's ID;
    ignore all other messages.
    Upon accepting a valid assignment, transition to the FLY phase, storing `pallet_id` and `generation_time`.
    Execute the cycle:
      FLY (hold for `flight_time`, then write 'depart' JSONL to stdout)
      -> UNLOAD (hold for `unload_time`, then emit `delivery_out` containing `aircraft_id`, `pallet_id`, `generation_time`)
      -> RETURN (hold for `return_time`, then write 'return' JSONL to stdout)
      -> MAINTENANCE (write 'maintenance_start' JSONL to stdout, hold for `maintenance_time`, then write 'maintenance_end' JSONL to stdout).
    After maintenance completes, emit `idle_out` and transition back to IDLE.
    Ignore any assignments received while not in IDLE state.
    """

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

        # Ports
        self.add_in_port(Port(dict, "assignment_in"))
        self.add_out_port(Port(dict, "idle_out"))
        self.add_out_port(Port(dict, "delivery_out"))

        # Internal state
        self.pallet_id = None
        self.generation_time = None

    def initialize(self):
        """Initialize state variables and schedule immediate idle output."""
        self.pallet_id = None
        self.generation_time = None
        # Schedule immediate output to emit idle_out at t=0
        self.hold_in("IDLE_OUTPUT", 0.0)

    def deltext(self, e: float):
        """Handle incoming assignments."""
        # We only accept assignments if we are in IDLE phase.
        # Note: The "IDLE" phase is the passive/waiting state.
        # "IDLE_OUTPUT" is a transient state used to emit the signal at t=0.
        if self.phase == "IDLE":
            for payload in self.input["assignment_in"].values:
                # Check if this assignment is for this aircraft
                if payload.get("aircraft_id") == self.aircraft_id:
                    self.pallet_id = payload.get("pallet_id")
                    self.generation_time = payload.get("generation_time")
                    # Transition to FLY phase
                    self.hold_in("FLY", self.flight_time)
                    break
        else:
            # If we are busy (FLY, UNLOAD, RETURN, MAINTENANCE, or output states),
            # we ignore assignments. We preserve the remaining time for the current phase.
            # The standard way to do this in xDEVS when ignoring input is to continue the current phase.
            # However, since we are using hold_in, we need to preserve sigma.
            # self.continuef(e) is the standard way to do this.
            self.continuef(e)

    def lambdaf(self):
        """Emit outputs based on the current phase."""
        now = get_current_time()

        if self.phase == "IDLE_OUTPUT":
            # Emit idle status
            self.output["idle_out"].add({"aircraft_id": self.aircraft_id})

        elif self.phase == "FLY":
            # Write 'depart' JSONL to stdout
            # Schema: {"time": <float>, "entity": "aircraft", "event": "depart", "payload": {...}}
            record = {
                "time": now,
                "entity": "aircraft",
                "event": "depart",
                "payload": {
                    "aircraft_id": self.aircraft_id,
                    "pallet_id": self.pallet_id
                }
            }
            print(json.dumps(record), flush=True)

        elif self.phase == "UNLOAD":
            # Emit delivery_out to Destination
            self.output["delivery_out"].add({
                "aircraft_id": self.aircraft_id,
                "pallet_id": self.pallet_id,
                "generation_time": self.generation_time
            })

        elif self.phase == "RETURN":
            # Write 'return' JSONL to stdout
            record = {
                "time": now,
                "entity": "aircraft",
                "event": "return",
                "payload": {
                    "aircraft_id": self.aircraft_id
                }
            }
            print(json.dumps(record), flush=True)

        elif self.phase == "MAINTENANCE_START":
            # Write 'maintenance_start' JSONL to stdout
            record = {
                "time": now,
                "entity": "aircraft",
                "event": "maintenance_start",
                "payload": {
                    "aircraft_id": self.aircraft_id
                }
            }
            print(json.dumps(record), flush=True)

        elif self.phase == "MAINTENANCE_END":
            # Write 'maintenance_end' JSONL to stdout
            record = {
                "time": now,
                "entity": "aircraft",
                "event": "maintenance_end",
                "payload": {
                    "aircraft_id": self.aircraft_id
                }
            }
            print(json.dumps(record), flush=True)

    def deltint(self):
        """Handle internal transitions based on the current phase."""
        if self.phase == "IDLE_OUTPUT":
            # After emitting idle, transition to passive IDLE state to wait for assignment
            self.passivate("IDLE")

        elif self.phase == "FLY":
            # Flight finished, move to UNLOAD
            self.hold_in("UNLOAD", self.unload_time)

        elif self.phase == "UNLOAD":
            # Unload finished, move to RETURN
            self.hold_in("RETURN", self.return_time)

        elif self.phase == "RETURN":
            # Return finished, move to MAINTENANCE_START (immediate output)
            self.hold_in("MAINTENANCE_START", 0.0)

        elif self.phase == "MAINTENANCE_START":
            # Maintenance start logged, now wait for maintenance duration
            self.hold_in("MAINTENANCE_END", self.maintenance_time)

        elif self.phase == "MAINTENANCE_END":
            # Maintenance finished, clear cargo data and emit idle signal
            self.pallet_id = None
            self.generation_time = None
            self.hold_in("IDLE_OUTPUT", 0.0)

    def exit(self):
        """Cleanup if necessary."""
        pass