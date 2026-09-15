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
        self.hold_in("INIT", 0)

    def initialize(self):
        self.hold_in("GENERATE", self.pallet_interval)

    def lambdaf(self):
        self.output["out"].add({
            "pallet_id": self.pallet_id_counter,
            "expiration_time": self.time + self.pallet_interval + 150.0  # Example expiration
        })

    def deltint(self):
        self.pallet_id_counter += 1
        self.hold_in("GENERATE", self.pallet_interval)

    def deltext(self, e):
        pass

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
        self.hold_in("INIT", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("IDLE", 0)

    def deltext(self, e):
        for event in self.input["in"].values:
            if "pallet_id" in event:
                self.queue.append(event)
                self.output["out"].add({
                    "pallet_id": event["pallet_id"],
                    "queue_size": len(self.queue)
                })
        self.hold_in("IDLE", 0)

    def exit(self):
        pass

class Coordinator(Atomic):
    def __init__(self, name: str, parent: Coupled | None, num_aircraft: int):
        super().__init__(name)
        self.parent = parent
        self.num_aircraft = num_aircraft
        self.aircraft_idle = [True] * num_aircraft
        self.pallet_queue = deque()
        self.add_in_port(Port(dict, "queue_in"))
        self.add_in_port(Port(dict, "aircraft_status"))
        self.add_out_port(Port(dict, "assignment"))
        self.add_out_port(Port(dict, "queue_out"))
        self.hold_in("INIT", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("IDLE", 0)

    def deltext(self, e):
        # Handle queue input
        for event in self.input["queue_in"].values:
            if "pallet_id" in event:
                self.pallet_queue.append(event)
                self.output["queue_out"].add(event)

        # Handle aircraft status
        for event in self.input["aircraft_status"].values:
            if "aircraft_id" in event:
                aircraft_id = event["aircraft_id"]
                if event.get("status") == "idle":
                    self.aircraft_idle[aircraft_id] = True
                elif event.get("status") == "busy":
                    self.aircraft_idle[aircraft_id] = False

        # Assign pallets to idle aircraft
        for i in range(self.num_aircraft):
            if self.aircraft_idle[i] and self.pallet_queue:
                pallet = self.pallet_queue.popleft()
                self.aircraft_idle[i] = False
                self.output["assignment"].add({
                    "aircraft_id": i,
                    "pallet_id": pallet["pallet_id"]
                })

        self.hold_in("IDLE", 0)

    def exit(self):
        pass

class Aircraft(Atomic):
    def __init__(self, name: str, parent: Coupled | None, aircraft_id: int, flight_time: float,
                 unload_time: float, return_time: float, maintenance_time: float):
        super().__init__(name)
        self.parent = parent
        self.aircraft_id = aircraft_id
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.state = "idle"
        self.pallet_id = None
        self.add_in_port(Port(dict, "assignment"))
        self.add_out_port(Port(dict, "status"))
        self.add_out_port(Port(dict, "delivery"))
        self.hold_in("IDLE", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        if self.state == "idle":
            self.hold_in("IDLE", 0)
        elif self.state == "loading":
            self.state = "flying"
            self.hold_in("FLYING", self.flight_time)
        elif self.state == "flying":
            self.state = "unloading"
            self.hold_in("UNLOADING", self.unload_time)
        elif self.state == "unloading":
            self.state = "returning"
            self.hold_in("RETURNING", self.return_time)
        elif self.state == "returning":
            self.state = "maintenance"
            self.hold_in("MAINTENANCE", self.maintenance_time)
        elif self.state == "maintenance":
            self.state = "idle"
            self.hold_in("IDLE", 0)
        else:
            self.hold_in("IDLE", 0)

    def deltext(self, e):
        for event in self.input["assignment"].values:
            if "aircraft_id" in event and event["aircraft_id"] == self.aircraft_id:
                self.pallet_id = event["pallet_id"]
                self.state = "loading"
                self.output["status"].add({
                    "aircraft_id": self.aircraft_id,
                    "status": "busy"
                })
                self.output["status"].add({
                    "aircraft_id": self.aircraft_id,
                    "status": "depart"
                })
                self.hold_in("LOADING", 0)  # Instantaneous loading
                return

        self.hold_in("IDLE", 0)

    def exit(self):
        pass

class Destination(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "delivery"))
        self.hold_in("INIT", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("IDLE", 0)

    def deltext(self, e):
        for event in self.input["delivery"].values:
            self.output["delivery"].add(event)
        self.hold_in("IDLE", 0)

    def exit(self):
        pass

class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None, duration: float, num_aircraft: int,
                 pallet_interval: float, pallet_expiration_time: float, flight_time: float,
                 unload_time: float, return_time: float, maintenance_time: float):
        super().__init__(name)
        self.parent = parent
        self.duration = duration

        # Create components
        self.facility = Facility(name="facility", parent=self, pallet_interval=pallet_interval)
        self.queue = Queue(name="queue", parent=self)
        self.coordinator = Coordinator(name="coordinator", parent=self, num_aircraft=num_aircraft)
        self.aircrafts = [Aircraft(name=f"aircraft_{i}", parent=self, aircraft_id=i,
                                   flight_time=flight_time, unload_time=unload_time,
                                   return_time=return_time, maintenance_time=maintenance_time)
                          for i in range(num_aircraft)]
        self.destination = Destination(name="destination", parent=self)

        # Add components
        self.add_component(self.facility)
        self.add_component(self.queue)
        self.add_component(self.coordinator)
        for aircraft in self.aircrafts:
            self.add_component(aircraft)
        self.add_component(self.destination)

        # Define couplings
        # Facility to Queue
        self.add_coupling(self.facility.output["out"], self.queue.input["in"])
        # Queue to Coordinator
        self.add_coupling(self.queue.output["out"], self.coordinator.input["queue_in"])
        # Coordinator to Aircraft
        for aircraft in self.aircrafts:
            self.add_coupling(self.coordinator.output["assignment"], aircraft.input["assignment"])
        # Aircraft to Coordinator (status updates)
        for aircraft in self.aircrafts:
            self.add_coupling(aircraft.output["status"], self.coordinator.input["aircraft_status"])
        # Aircraft to Destination
        for aircraft in self.aircrafts:
            self.add_coupling(aircraft.output["delivery"], self.destination.input["delivery"])

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

    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.duration)

if __name__ == "__main__":
    main()