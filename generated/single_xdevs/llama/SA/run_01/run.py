import argparse
import json
import logging
import random
import sys
from collections import defaultdict
from typing import Dict, List

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Configure logging
logging.basicConfig(stream=sys.stderr, level=logging.INFO)

class Facility(Atomic):
    def __init__(self, name: str, parent: Coupled | None, pallet_interval: float):
        super().__init__(name)
        self.parent = parent
        self.pallet_interval = pallet_interval
        self.pallet_id = 0
        self.add_out_port(Port("pallet", "pallet"))

    def initialize(self):
        self.pallet_id = 0
        self.output["pallet"].add({"pallet_id": self.pallet_id, "expiration_time": self.pallet_interval})
        self.hold_in("idle", self.pallet_interval)

    def lambdaf(self):
        pass

    def deltint(self):
        self.pallet_id += 1
        self.output["pallet"].add({"pallet_id": self.pallet_id, "expiration_time": self.pallet_id * self.pallet_interval})
        self.hold_in("idle", self.pallet_interval)

    def deltext(self, e):
        pass

    def exit(self):
        pass

class LoadingQueue(Atomic):
    def __init__(self, name: str, parent: Coupled | None, pallet_expiration_time: float):
        super().__init__(name)
        self.parent = parent
        self.pallet_expiration_time = pallet_expiration_time
        self.pallets: Dict[int, float] = {}
        self.add_in_port(Port("pallet", "pallet"))
        self.add_out_port(Port("pallet", "expired_pallet"))
        self.add_out_port(Port("pallet", "queued_pallet"))

    def initialize(self):
        self.pallets = {}
        self.hold_in("idle", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        for pallet_id, expiration_time in list(self.pallets.items()):
            if expiration_time <= self.time:
                self.pallets.pop(pallet_id)
                self.output["expired_pallet"].add({"pallet_id": pallet_id, "total_expired": len(self.pallets)})
                logging.info(f"Pallet {pallet_id} expired at time {self.time}")

    def deltext(self, e):
        for msg in self.input["pallet"].values:
            pallet_id = msg["pallet_id"]
            expiration_time = msg["expiration_time"]
            self.pallets[pallet_id] = expiration_time
            self.output["queued_pallet"].add({"pallet_id": pallet_id, "queue_size": len(self.pallets)})

    def exit(self):
        pass

class FleetCoordinator(Atomic):
    def __init__(self, name: str, parent: Coupled | None, num_aircraft: int):
        super().__init__(name)
        self.parent = parent
        self.num_aircraft = num_aircraft
        self.aircraft: List[dict] = [{"id": i, "status": "idle"} for i in range(num_aircraft)]
        self.add_in_port(Port("pallet", "pallet"))
        self.add_out_port(Port("pallet", "assigned_pallet"))

    def initialize(self):
        self.hold_in("idle", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        available_aircraft = [aircraft for aircraft in self.aircraft if aircraft["status"] == "idle"]
        if available_aircraft:
            for msg in self.input["pallet"].values:
                pallet_id = msg["pallet_id"]
                aircraft = random.choice(available_aircraft)
                aircraft["status"] = "in-flight"
                self.output["assigned_pallet"].add({"aircraft_id": aircraft["id"], "pallet_id": pallet_id})

    def deltext(self, e):
        pass

    def exit(self):
        pass

class Aircraft(Atomic):
    def __init__(self, name: str, parent: Coupled | None, flight_time: float, unload_time: float, return_time: float, maintenance_time: float):
        super().__init__(name)
        self.parent = parent
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.status = "idle"
        self.pallet_id = None
        self.add_in_port(Port("pallet", "assigned_pallet"))

    def initialize(self):
        self.status = "idle"
        self.pallet_id = None
        self.hold_in("idle", 0)

    def lambdaf(self):
        if self.status == "in-flight":
            self.output["status"].add({"aircraft_id": self.name, "status": self.status})
        elif self.status == "unloading":
            self.output["pallet_delivered"].add({"pallet_id": self.pallet_id, "aircraft_id": self.name})

    def deltint(self):
        if self.status == "idle":
            self.status = "loading"
            self.hold_in("loading", 0)
        elif self.status == "loading":
            self.status = "in-flight"
            self.hold_in("in-flight", self.flight_time)
        elif self.status == "in-flight":
            self.status = "unloading"
            self.hold_in("unloading", self.unload_time)
        elif self.status == "unloading":
            self.status = "returning"
            self.hold_in("returning", self.return_time)
        elif self.status == "returning":
            self.status = "maintenance"
            self.hold_in("maintenance", self.maintenance_time)
        elif self.status == "maintenance":
            self.status = "idle"
            self.hold_in("idle", 0)

    def deltext(self, e):
        for msg in self.input["assigned_pallet"].values:
            self.pallet_id = msg["pallet_id"]
            self.status = "loading"
            self.hold_in("loading", 0)

    def exit(self):
        pass

class Destination(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("pallet", "pallet_delivered"))

    def initialize(self):
        self.hold_in("idle", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        for msg in self.input["pallet_delivered"].values:
            pallet_id = msg["pallet_id"]
            aircraft_id = msg["aircraft_id"]
            latency = self.time - msg["generation_time"]
            print(json.dumps({"time": self.time, "entity": "destination", "event": "pallet_delivered", "payload": {"pallet_id": pallet_id, "aircraft_id": aircraft_id, "latency": latency}}), file=sys.stdout, flush=True)

    def exit(self):
        pass

class AirfreightLogistics(Coupled):
    def __init__(self, name: str, parent: Coupled | None, config: dict):
        super().__init__(name)
        self.parent = parent

        self.facility = Facility(name="facility", parent=self, pallet_interval=config["pallet_interval"])
        self.add_component(self.facility)

        self.loading_queue = LoadingQueue(name="loading_queue", parent=self, pallet_expiration_time=config["pallet_expiration_time"])
        self.add_component(self.loading_queue)

        self.coordinator = FleetCoordinator(name="coordinator", parent=self, num_aircraft=config["num_aircraft"])
        self.add_component(self.coordinator)

        self.aircraft = []
        for i in range(config["num_aircraft"]):
            aircraft = Aircraft(name=f"aircraft_{i}", parent=self, flight_time=config["flight_time"], unload_time=config["unload_time"], return_time=config["return_time"], maintenance_time=config["maintenance_time"])
            self.add_component(aircraft)
            self.aircraft.append(aircraft)

        self.destination = Destination(name="destination", parent=self)
        self.add_component(self.destination)

        self.add_coupling(self.facility.output["pallet"], self.loading_queue.input["pallet"])
        self.add_coupling(self.loading_queue.output["queued_pallet"], self.coordinator.input["pallet"])
        self.add_coupling(self.coordinator.output["assigned_pallet"], [aircraft.input["assigned_pallet"] for aircraft in self.aircraft])
        self.add_coupling([aircraft.output["pallet_delivered"] for aircraft in self.aircraft], self.destination.input["pallet_delivered"])

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

    config = {
        "duration": args.duration,
        "num_aircraft": args.num_aircraft,
        "pallet_interval": args.pallet_interval,
        "pallet_expiration_time": args.pallet_expiration_time,
        "flight_time": args.flight_time,
        "unload_time": args.unload_time,
        "return_time": args.return_time,
        "maintenance_time": args.maintenance_time,
    }

    root = AirfreightLogistics(name="airfreight_logistics", parent=None, config=config)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.duration)

if __name__ == "__main__":
    main()