<python_code>
import argparse
import sys
import json
import time
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

class Facility(Atomic):
    def __init__(self, name: str, parent: Coupled, pallet_interval: float):
        super().__init__(name)
        self.parent = parent
        self.pallet_interval = pallet_interval
        self.pallet_id = 0
        self.add_out_port(Port(dict, "out"))
        self.hold_in("GENERATE", 0)

    def initialize(self):
        self.hold_in("GENERATE", 0)

    def lambdaf(self):
        self.output["out"].add({
            "pallet_id": self.pallet_id,
            "expiration_time": self.sigma + self.pallet_interval + 100  # dummy expiration time for now
        })

    def deltint(self):
        self.pallet_id += 1
        self.hold_in("GENERATE", self.pallet_interval)

    def deltext(self, e):
        pass

    def exit(self):
        pass

class Queue(Atomic):
    def __init__(self, name: str, parent: Coupled, pallet_expiration_time: float):
        super().__init__(name)
        self.parent = parent
        self.pallet_expiration_time = pallet_expiration_time
        self.queue = deque()
        self.total_expired = 0
        self.add_in_port(Port(dict, "in"))
        self.add_out_port(Port(dict, "out"))
        self.add_out_port(Port(dict, "expired"))
        self.hold_in("IDLE", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.queue:
            pallet = self.queue[0]
            self.output["out"].add({
                "pallet_id": pallet["pallet_id"],
                "queue_size": len(self.queue)
            })

    def deltint(self):
        if self.queue:
            pallet = self.queue[0]
            if self.sigma >= pallet["expiration_time"]:
                self.queue.popleft()
                self.total_expired += 1
                self.output["expired"].add({
                    "pallet_id": pallet["pallet_id"],
                    "total_expired": self.total_expired
                })
                self.hold_in("IDLE", 0)
            else:
                self.hold_in("IDLE", self.sigma - self.sigma)
        else:
            self.hold_in("IDLE", 0)

    def deltext(self, e):
        if e == "in":
            for msg in self.input["in"].values:
                self.queue.append(msg)
                # Update expiration time
                msg["expiration_time"] = self.sigma + self.pallet_expiration_time
                # Log pallet queued
                print(json.dumps({
                    "time": self.sigma,
                    "entity": "queue",
                    "event": "pallet_queued",
                    "payload": {
                        "pallet_id": msg["pallet_id"],
                        "queue_size": len(self.queue)
                    }
                }), file=sys.stdout, flush=True)
                # Check if expired
                if self.sigma >= msg["expiration_time"]:
                    self.queue.popleft()
                    self.total_expired += 1
                    self.output["expired"].add({
                        "pallet_id": msg["pallet_id"],
                        "total_expired": self.total_expired
                    })
                    # Log pallet expired
                    print(json.dumps({
                        "time": self.sigma,
                        "entity": "queue",
                        "event": "pallet_expired",
                        "payload": {
                            "pallet_id": msg["pallet_id"],
                            "total_expired": self.total_expired
                        }
                    }), file=sys.stdout, flush=True)
                    self.hold_in("IDLE", 0)
                else:
                    self.hold_in("IDLE", self.sigma - self.sigma)
        elif e == "expired":
            for msg in self.input["expired"].values:
                self.total_expired += 1
                self.output["expired"].add(msg)
                self.hold_in("IDLE", 0)
        else:
            self.hold_in("IDLE", 0)

    def exit(self):
        pass

class Coordinator(Atomic):
    def __init__(self, name: str, parent: Coupled, num_aircraft: int):
        super().__init__(name)
        self.parent = parent
        self.num_aircraft = num_aircraft
        self.aircraft_states = [None] * num_aircraft  # [None, "idle", "loading", "flying", "unloading", "returning", "maintenance"]
        self.aircraft_assignments = {}  # aircraft_id -> pallet_id
        self.add_in_port(Port(dict, "queue_in"))
        self.add_in_port(Port(dict, "aircraft_status"))
        self.add_out_port(Port(dict, "assignment"))
        self.hold_in("IDLE", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("IDLE", 0)

    def deltext(self, e):
        if e == "queue_in":
            for msg in self.input["queue_in"].values:
                # Find idle aircraft
                idle_aircraft = None
                for i in range(self.num_aircraft):
                    if self.aircraft_states[i] is None or self.aircraft_states[i] == "idle":
                        idle_aircraft = i
                        break
                if idle_aircraft is not None:
                    self.aircraft_states[idle_aircraft] = "loading"
                    self.aircraft_assignments[idle_aircraft] = msg["pallet_id"]
                    # Log assignment
                    print(json.dumps({
                        "time": self.sigma,
                        "entity": "coordinator",
                        "event": "assignment_created",
                        "payload": {
                            "aircraft_id": idle_aircraft,
                            "pallet_id": msg["pallet_id"]
                        }
                    }), file=sys.stdout, flush=True)
                    # Output assignment