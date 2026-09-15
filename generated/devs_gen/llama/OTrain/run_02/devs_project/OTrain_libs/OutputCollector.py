"""Complete pattern: external JSONL output owned by an atomic sink."""

import json
from xdevs.models import Atomic, Coupled, Port


class OutputCollector(Atomic):
    """Write only received business records to stdout as JSONL."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "passenger_generated"))
        self.add_in_port(Port(dict, "train_arrival"))
        self.add_in_port(Port(dict, "passenger_boarding"))
        self.add_in_port(Port(dict, "passenger_exiting"))

    def initialize(self):
        self.passivate("WAITING")

    def deltext(self, e):
        for event in self.input["passenger_generated"].values:
            print(json.dumps({"time": event["time"], "event": "passenger_generated", "entity_type": "passenger_generator", "station_id": event["origin"], "station": ["Bayview", "Carling", "Carleton", "Confed", "Greenboro"][event["origin"] - 1], "payload": {"passenger_id": event["passenger_id"], "passenger_num": event["passenger_num"], "origin": event["origin"], "destination": event["destination"]}}), flush=True)
        for event in self.input["train_arrival"].values:
            print(json.dumps({"time": event["time"], "event": "train_arrival", "entity_type": "train", "station_id": event["station"], "station": ["Bayview", "Carling", "Carleton", "Confed", "Greenboro"][event["station"] - 1], "payload": {"station": event["station"], "direction": event["direction"]}}), flush=True)
        for event in self.input["passenger_boarding"].values:
            print(json.dumps({"time": event["time"], "event": "passenger_boarding", "entity_type": "station_queue", "station_id": event["origin"], "station": ["Bayview", "Carling", "Carleton", "Confed", "Greenboro"][event["origin"] - 1], "payload": {"passenger_id": event["passenger_id"], "passenger_num": event["passenger_num"], "origin": event["origin"], "destination": event["destination"]}}), flush=True)
        for event in self.input["passenger_exiting"].values:
            print(json.dumps({"time": event["time"], "event": "passenger_exiting", "entity_type": "train_queue", "station_id": event["destination"], "station": ["Bayview", "Carling", "Carleton", "Confed", "Greenboro"][event["destination"] - 1], "payload": {"passenger_id": event["passenger_id"], "passenger_num": event["passenger_num"], "origin": event["origin"], "destination": event["destination"]}}), flush=True)
        self.passivate("WAITING")

    def lambdaf(self):
        # A pure sink has no DEVS output ports.
        pass

    def deltint(self):
        self.passivate("WAITING")

    def exit(self):
        # Never print lifecycle or diagnostic records to stdout.
        pass