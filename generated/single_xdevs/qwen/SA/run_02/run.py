import argparse
import sys
import json
import random
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

class Facility(Atomic):
    def __init__(self, name: str, parent: Coupled | None, pallet_interval: float):
        super().__init__(name)
        self.parent = parent
        self.pallet_interval = pallet_interval
        self.pallet_id_counter = 0
        self.add_out_port(Port(dict, "out"))
        self.hold_in("GENERATE", 0)

    def initialize(self):
        self.hold_in("GENERATE", 0)

    def lambdaf(self):
        self.output["out"].add({
            "time": self.clock.time,
            "entity": "facility",
            "event": "pallet_generated",
            "payload": {
                "pallet_id": self.pallet_id_counter,
                "expiration_time": self.clock.time + self.pallet_interval + 150.0
            }
        })

    def deltint(self):
        self.pallet_id_counter += 1
        self.hold_in("GENERATE", self.pallet_interval)

    def deltext(self, e):
        self.hold_in("GENERATE", self.pallet_interval)

    def exit(self):
        pass

class Queue(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.queue = deque()
        self.total_expired = 0
        self.add_in_port(Port(dict, "in"))
        self.add_out_port(Port(dict, "out"))
        self.add_out_port(Port(dict, "expired"))
        self.hold_in("IDLE", float('inf'))

    def initialize(self):
        self.hold_in("IDLE", float('inf'))

    def lambdaf(self):
        pass

    def deltint(self):
        # Check for expired pallets
        expired_count = 0
        current_time = self.clock.time
        while self.queue and self.queue[0]["expiration_time"] <= current_time:
            pallet = self.queue.popleft()
            self.total_expired += 1
            self.output["expired"].add({
                "time": current_time,
                "entity": "queue",
                "event": "pallet_expired",
                "payload": {
                    "pallet_id": pallet["pallet_id"],
                    "total_expired": self.total_expired
                }
            })
            expired_count += 1
        if expired_count > 0:
            self.hold_in("IDLE", 0)
        else:
            self.hold_in("IDLE", float('inf'))

    def deltext(self, e):
        if self.input["in"].values:
            for msg in self.input["in"].values:
                self.queue.append(msg)
                self.output["out"].add({
                    "time": self.clock.time,
                    "entity": "queue",
                    "event": "pallet_queued",
                    "payload": {
                        "pallet_id": msg["pallet_id"],
                        "queue_size": len(self.queue)
                    }
                })
            self.hold_in("IDLE", 0)
        else:
            self.hold_in("IDLE", float('inf'))

    def exit(self):
        pass

class Coordinator(Atomic):
    def __init__(self, name: str, parent: Coupled | None, num_aircraft: int):
        super().__init__(name)
        self.parent = parent
        self.num_aircraft = num_aircraft
        self.aircraft_states = {i: "IDLE" for i in range(num_aircraft)}
        self.pending_assignments = {}
        self.add_in_port(Port(dict, "queue"))
        self.add_in_port(Port(dict, "aircraft"))
        self.add_out_port(Port(dict, "assignment"))
        self.hold_in("IDLE", float('inf'))

    def initialize(self):
        self.hold_in("IDLE", float('inf'))

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("IDLE", float('inf'))

    def deltext(self, e):
        # Process queue input
        if self.input["queue"].values:
            for msg in self.input["queue"].values:
                # Assign to first available aircraft
                assigned_aircraft = None
                for aid, state in self.aircraft_states.items():
                    if state == "IDLE":
                        assigned_aircraft = aid
                        break
                if assigned_aircraft is not None:
                    self.aircraft_states[assigned_aircraft] = "LOADING"
                    self.output["assignment"].add({
                        "time": self.clock.time,
                        "entity": "coordinator",
                        "event": "assignment_created",
                        "payload": {
                            "aircraft_id": assigned_aircraft,
                            "pallet_id": msg["pallet_id"]
                        }
                    })
                    self.pending_assignments[assigned_aircraft] = msg
        # Process aircraft input
        if self.input["aircraft"].values:
            for msg in self.input["aircraft"].values:
                aid = msg["aircraft_id"]
                event = msg["event"]
                if event == "depart":
                    self.aircraft_states[aid] = "FLYING"
                elif event == "return":
                    self.aircraft_states[aid] = "RETURNING"
                elif event == "maintenance_start":
                    self.aircraft_states[aid] = "MAINTENANCE"
                elif event == "maintenance_end":
                    self.aircraft_states[aid] = "IDLE"
                    if aid in self.pending_assignments:
                        del self.pending_assignments[aid]
        self.hold_in("IDLE", float('inf'))

    def exit(self):
        pass

class Aircraft(Atomic):
    def __init__(self, name: str, parent: Coupled | None, aircraft_id: int, flight_time: float, unload_time: float, return_time: float, maintenance_time: float):
        super().__init__(name)
        self.parent = parent
        self.aircraft_id = aircraft_id
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.state = "IDLE"
        self.pallet_id = None
        self.gen_time = None
        self.add_in_port(Port(dict, "assignment"))
        self.add_out_port(Port(dict, "status"))
        self.add_out_port(Port(dict, "delivery"))
        self.hold_in("IDLE", float('inf'))

    def initialize(self):
        self.hold_in("IDLE", float('inf'))

    def lambdaf(self):
        pass

    def deltint(self):
        if self.state == "LOADING":
            self.state = "FLYING"
            self.output["status"].add({
                "time": self.clock.time,
                "entity": "aircraft",
                "event": "depart",
                "payload": {
                    "aircraft_id": self.aircraft_id,
                    "pallet_id": self.pallet_id
                }
            })
            self.hold_in("FLYING", self.flight_time)
        elif self.state == "FLYING":
            self.state = "UNLOADING"
            self.output["status"].add({
                "time": self.clock.time,
                "entity": "aircraft",
                "event": "unload_start",
                "payload": {
                    "aircraft_id": self.aircraft_id,
                    "pallet_id": self.pallet_id
                }
            })
            self.hold_in("UNLOADING", self.unload_time)
        elif self.state == "UNLOADING":
            self.state = "RETURNING"
            self.output["delivery"].add({
                "time": self.clock.time,
                "entity": "destination",
                "event": "pallet_delivered",
                "payload": {
                    "pallet_id": self.pallet_id,
                    "aircraft_id": self.aircraft_id,
                    "latency": self.clock.time - self.gen_time
                }
            })
            self.hold_in("RETURNING", self.return_time)
        elif self.state == "RETURNING":
            self.state = "MAINTENANCE"
            self.output["status"].add({
                "time": self.clock.time,
                "entity": "aircraft",
                "event": "maintenance_start",
                "payload": {
                    "aircraft_id": self.aircraft_id
                }
            })
            self.hold_in("MAINTENANCE", self.maintenance_time)
        elif self.state == "MAINTENANCE":
            self.state = "IDLE"
            self.output["status"].add({
                "time": self.clock.time,
                "entity": "aircraft",
                "event": "maintenance_end",
                "payload": {
                    "aircraft_id": self.aircraft_id
                }
            })
            self.hold_in("IDLE", 0)
        else:
            self.hold_in("IDLE", float('inf'))

    def deltext(self, e):
        if self.input["assignment"].values:
            for msg in self.input["assignment"].values:
                self.pallet_id = msg["pallet_id"]
                self.gen_time = msg["generation_time"]
                self.state = "LOADING"
                self.hold_in("LOADING", 0)
        else:
            self.hold_in("IDLE", float('inf'))

    def exit(self):
        pass

class Destination(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "delivery"))
        self.hold_in("IDLE", float('inf'))

    def initialize(self):
        self.hold_in("IDLE", float('inf'))

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("IDLE", float('inf'))

    def deltext(self, e):
        if self.input["delivery"].values:
            for msg in self.input["delivery"].values:
                # Already logged in Aircraft
                pass
        self.hold_in("IDLE", float('inf'))

    def exit(self):
        pass

class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None, duration: float, num_aircraft: int, pallet_interval: float, pallet_expiration_time: float, flight_time: float, unload_time: float, return_time: float, maintenance_time: float):
        super().__init__(name)
        self.parent = parent
        self.duration = duration
        self.num_aircraft = num_aircraft
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time

        # Create components
        self.facility = Facility(name="facility", parent=self, pallet_interval=pallet_interval)
        self.queue = Queue(name="queue", parent=self)
        self.coordinator = Coordinator(name="coordinator", parent=self, num_aircraft=num_aircraft)
        self.aircrafts = [Aircraft(name=f"aircraft_{i}", parent=self, aircraft_id=i, flight_time=flight_time, unload_time=unload_time, return_time=return_time, maintenance_time=maintenance_time) for i in range(num_aircraft)]
        self.destination = Destination(name="destination", parent=self)

        # Add components
        self.add_component(self.facility)
        self.add_component(self.queue)
        self.add_component(self.coordinator)
        for aircraft in self.aircrafts:
            self.add_component(aircraft)
        self.add_component(self.destination)

        # Define couplings
        # Facility -> Queue
        self.add_coupling(self.facility.output["out"], self.queue.input["in"])
        # Queue -> Coordinator
        self.add_coupling(self.queue.output["out"], self.coordinator.input["queue"])
        # Queue -> Coordinator (expired)
        self.add_coupling(self.queue.output["expired"], self.coordinator.input["queue"])
        # Coordinator -> Aircraft
        self.add_coupling(self.coordinator.output["assignment"], self.aircrafts[0].input["assignment"])
        self.add_coupling(self.coordinator.output["assignment"], self.aircrafts[1].input["assignment"])
        # Aircraft -> Coordinator
        self.add_coupling(self.aircrafts[0].output["status"], self.coordinator.input["aircraft"])
        self.add_coupling(self.aircrafts[1].output["status"], self.coordinator.input["aircraft"])
        self.add_coupling(self.aircrafts[0].output["delivery"], self.destination.input["delivery"])
        self.add_coupling(self.aircrafts[1].output["delivery"], self.destination.input["delivery"])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=10000.0)
    parser.add_argument("--num_aircraft", type=int, default=2)
    parser.add_argument("--pallet_interval", type=float, default=25.0)
    parser.add_argument("--pallet_expiration_time", type=float, default=150.0)
    parser.add_argument("--flight_time", type=float, default=30.0)
    parser.add_argument("--unload_time", type=float, default=2.0)
    parser.add_argument("--return_time", type=float, default=30.0)
    parser.add_argument("--maintenance_time", type=float, default=10.0)
    args = parser.parse_args()

    # Create system
    root = System(
        name="system",
        parent=None,
        duration=args.duration,
        num_aircraft=args.num_aircraft,
        pallet_interval=args.pallet_interval,
        pallet_expiration_time=args.pallet_expiration_time,
        flight_time=args.flight_time,
        unload_time=args.unload_time,
        return_time=args.return_time,
        maintenance_time=args.maintenance_time
    )
    
    # Run simulation
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.duration)

if __name__ == "__main__":
    main()