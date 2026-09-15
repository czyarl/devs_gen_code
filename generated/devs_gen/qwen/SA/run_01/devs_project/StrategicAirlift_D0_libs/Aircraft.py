import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Aircraft(Atomic):
    """Manage the lifecycle of one aircraft in an airfreight logistics simulation."""

    def __init__(self, name: str, parent: Coupled | None, aircraft_id: int, flight_time: float, unload_time: float, return_time: float, maintenance_time: float):
        super().__init__(name)
        self.parent = parent
        self.aircraft_id = aircraft_id
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.add_in_port(Port(dict, "assignment_in"))
        self.add_out_port(Port(dict, "available_out"))
        self.add_out_port(Port(dict, "delivery_out"))
        self.current_assignment = None
        self.state = "IDLE"
        self.next_state = None
        self.state_time = 0.0

    def initialize(self):
        # Emit initial availability at t=0
        self.hold_in("ANNOUNCE_AVAILABLE", 0.0)

    def deltext(self, e):
        if self.phase == "IDLE":
            # Check for new assignments
            for assignment in self.input["assignment_in"].values:
                if assignment["aircraft_id"] == self.aircraft_id:
                    self.current_assignment = dict(assignment)
                    self.state = "LOAD"
                    self.next_state = "FLY"
                    self.state_time = 0.0
                    self.hold_in("LOAD", 0.0)
                    return
            self.passivate("IDLE")
        elif self.phase == "LOAD":
            self.continuef(e)
        elif self.phase == "FLY":
            self.continuef(e)
        elif self.phase == "UNLOAD":
            self.continuef(e)
        elif self.phase == "RETURN":
            self.continuef(e)
        elif self.phase == "MAINTAIN":
            self.continuef(e)
        elif self.phase == "ANNOUNCE_AVAILABLE":
            self.continuef(e)
        else:
            self.passivate("IDLE")

    def lambdaf(self):
        now = get_current_time()
        if self.phase == "ANNOUNCE_AVAILABLE":
            # Emit initial availability
            self.output["available_out"].add({"aircraft_id": self.aircraft_id})
            print(json.dumps({
                "time": now,
                "entity": "aircraft",
                "event": "maintenance_end",
                "payload": {"aircraft_id": self.aircraft_id}
            }), flush=True)
        elif self.phase == "LOAD":
            # Load is instantaneous, move to fly
            self.state = "FLY"
            self.next_state = "UNLOAD"
            self.state_time = 0.0
            self.hold_in("FLY", self.flight_time)
        elif self.phase == "FLY":
            # Flight completed, move to unload
            self.state = "UNLOAD"
            self.next_state = "RETURN"
            self.state_time = 0.0
            self.hold_in("UNLOAD", self.unload_time)
        elif self.phase == "UNLOAD":
            # Unload completed, send delivery
            self.output["delivery_out"].add({
                "pallet_id": self.current_assignment["pallet_id"],
                "aircraft_id": self.aircraft_id,
                "generation_time": self.current_assignment["generation_time"]
            })
            print(json.dumps({
                "time": now,
                "entity": "destination",
                "event": "pallet_delivered",
                "payload": {
                    "pallet_id": self.current_assignment["pallet_id"],
                    "aircraft_id": self.aircraft_id,
                    "latency": now - self.current_assignment["generation_time"]
                }
            }), flush=True)
            self.state = "RETURN"
            self.next_state = "MAINTAIN"
            self.state_time = 0.0
            self.hold_in("RETURN", self.return_time)
        elif self.phase == "RETURN":
            # Return completed, move to maintain
            self.state = "MAINTAIN"
            self.next_state = "IDLE"
            self.state_time = 0.0
            self.hold_in("MAINTAIN", self.maintenance_time)
        elif self.phase == "MAINTAIN":
            # Maintenance completed, announce availability
            self.state = "IDLE"
            self.current_assignment = None
            self.output["available_out"].add({"aircraft_id": self.aircraft_id})
            print(json.dumps({
                "time": now,
                "entity": "aircraft",
                "event": "maintenance_end",
                "payload": {"aircraft_id": self.aircraft_id}
            }), flush=True)
        elif self.phase == "IDLE":
            # This should not be reached in lambdaf but just in case
            pass

    def deltint(self):
        # Internal transitions
        if self.phase == "LOAD":
            self.state = "FLY"
            self.next_state = "UNLOAD"
            self.state_time = 0.0
            self.hold_in("FLY", self.flight_time)
        elif self.phase == "FLY":
            self.state = "UNLOAD"
            self.next_state = "RETURN"
            self.state_time = 0.0
            self.hold_in("UNLOAD", self.unload_time)
        elif self.phase == "UNLOAD":
            self.state = "RETURN"
            self.next_state = "MAINTAIN"
            self.state_time = 0.0
            self.hold_in("RETURN", self.return_time)
        elif self.phase == "RETURN":
            self.state = "MAINTAIN"
            self.next_state = "IDLE"
            self.state_time = 0.0
            self.hold_in("MAINTAIN", self.maintenance_time)
        elif self.phase == "MAINTAIN":
            self.state = "IDLE"
            self.current_assignment = None
            self.output["available_out"].add({"aircraft_id": self.aircraft_id})
            print(json.dumps({
                "time": get_current_time(),
                "entity": "aircraft",
                "event": "maintenance_end",
                "payload": {"aircraft_id": self.aircraft_id}
            }), flush=True)
        elif self.phase == "ANNOUNCE_AVAILABLE":
            # Do nothing, already handled in lambdaf
            pass
        else:
            self.passivate("IDLE")

    def exit(self):
        pass