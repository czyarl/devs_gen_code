import argparse
import json
import logging
import random
import sys
import time
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Constants
STATIONS = {
    1: "Bayview",
    2: "Carling",
    3: "Carleton",
    4: "Confed",
    5: "Greenboro",
}

DIRECTIONS = {
    0: "Southbound",
    1: "Northbound",
}

class PassengerGenerator(Atomic):
    def __init__(self, name: str, parent: Coupled | None, station_id: int):
        super().__init__(name)
        self.parent = parent
        self.station_id = station_id
        self.passenger_num = 0
        self.add_out_port(Port("passenger_generated", "out"))

    def initialize(self):
        self.passenger_num = 0
        self.generate_passenger(0.5)
        self.hold_in("WAIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("WAIT", 0)

    def deltext(self, e):
        self.hold_in("WAIT", 0)

    def exit(self):
        pass

    def generate_passenger(self, time):
        origin = self.station_id
        destination = random.choice([i for i in STATIONS.keys() if i != origin])
        passenger_id = self.passenger_num * 100 + origin * 10 + destination
        payload = {
            "passenger_id": passenger_id,
            "passenger_num": self.passenger_num,
            "origin": origin,
            "destination": destination,
        }
        self.output["out"].add(payload)
        logging.debug(f"Passenger generated at station {origin}: {passenger_id}")
        self.passenger_num += 1
        interval = max(1, min(9, random.gauss(5, 5))) * 60
        interval = round(interval)
        self.hold_in("WAIT", interval)


class StationQueue(Atomic):
    def __init__(self, name: str, parent: Coupled | None, station_id: int):
        super().__init__(name)
        self.parent = parent
        self.station_id = station_id
        self.queue = deque()
        self.add_in_port(Port("passenger_generated", "in"))
        self.add_out_port(Port("passenger_boarding", "out"))

    def initialize(self):
        self.queue.clear()
        self.hold_in("WAIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("WAIT", 0)

    def deltext(self, e):
        for msg in self.input["in"].values:
            payload = msg["payload"]
            self.queue.append(payload)
        self.input["in"].clear()
        self.hold_in("WAIT", 0)

    def exit(self):
        pass

    def board_passenger(self, time):
        if self.queue:
            payload = self.queue.popleft()
            self.output["out"].add(payload)
            logging.debug(f"Passenger {payload['passenger_id']} boarded at station {self.station_id}")


class Train(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.station_id = 1
        self.direction = 0
        self.passengers = []
        self.add_out_port(Port("train_arrival", "out"))
        self.add_out_port(Port("passenger_exiting", "exiting"))

    def initialize(self):
        self.station_id = 1
        self.direction = 0
        self.passengers = []
        self.arrive_at_station(0.0)
        self.hold_in("WAIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("WAIT", 0)

    def deltext(self, e):
        self.hold_in("WAIT", 0)

    def exit(self):
        pass

    def arrive_at_station(self, time):
        self.output["out"].add({
            "station_id": self.station_id,
            "station": STATIONS[self.station_id],
            "direction": self.direction,
        })
        logging.debug(f"Train arrived at station {self.station_id}")
        self.alight_passengers(time)
        self.board_passengers(time)
        self.move_to_next_station(time)

    def alight_passengers(self, time):
        exiting_passengers = [p for p in self.passengers if p["destination"] == self.station_id]
        for passenger in exiting_passengers:
            self.output["exiting"].add(passenger)
            logging.debug(f"Passenger {passenger['passenger_id']} exited at station {self.station_id}")
        self.passengers = [p for p in self.passengers if p["destination"] != self.station_id]

    def board_passengers(self, time):
        # Assume station queue will send boarding events

    def move_to_next_station(self, time):
        if self.direction == 0:
            if self.station_id < 5:
                self.station_id += 1
            else:
                self.station_id = 4
                self.direction = 1
        else:
            if self.station_id > 1:
                self.station_id -= 1
            else:
                self.station_id = 2
                self.direction = 0
        self.hold_in("WAIT", 225)


class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.train = Train(name="train", parent=self)
        self.add_component(self.train)
        self.station_queues = []
        self.passenger_generators = []
        for i in range(1, 6):
            station_queue = StationQueue(name=f"station_queue_{i}", parent=self, station_id=i)
            self.add_component(station_queue)
            self.station_queues.append(station_queue)
            passenger_generator = PassengerGenerator(name=f"passenger_generator_{i}", parent=self, station_id=i)
            self.add_component(passenger_generator)
            self.passenger_generators.append(passenger_generator)
        self.add_coupling(self.train.output["out"], self.station_queues[0].input["in"])
        for i in range(5):
            self.add_coupling(self.passenger_generators[i].output["out"], self.station_queues[i].input["in"])
            self.add_coupling(self.train.output["out"], self.passenger_generators[i].input["in"])
        self.add_coupling(self.station_queues[0].output["out"], self.train.input["in"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate_time", type=str, default="00:01:00:000")
    args = parser.parse_args()
    hours, minutes, seconds, milliseconds = map(int, args.simulate_time.split(":"))
    simulate_time = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000

    root = System(name="system", parent=None)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(simulate_time)

    for event in root.train.output["exiting"].values:
        print(json.dumps({
            "time": event["time"],
            "event": "passenger_exiting",
            "entity_type": "train_queue",
            "station_id": event["station"],
            "station": STATIONS[event["station"]],
            "payload": event,
        }), file=sys.stdout, flush=True)

    for event in root.train.output["out"].values:
        print(json.dumps({
            "time": event["time"],
            "event": "train_arrival",
            "entity_type": "train",
            "station_id": event["station_id"],
            "station": event["station"],
            "payload": event,
        }), file=sys.stdout, flush=True)

    for generator in root.passenger_generators:
        for event in generator.output["out"].values:
            print(json.dumps({
                "time": event["time"],
                "event": "passenger_generated",
                "entity_type": "passenger_generator",
                "station_id": event["payload"]["origin"],
                "station": STATIONS[event["payload"]["origin"]],
                "payload": event["payload"],
            }), file=sys.stdout, flush=True)

    for queue in root.station_queues:
        for event in queue.output["out"].values:
            print(json.dumps({
                "time": event["time"],
                "event": "passenger_boarding",
                "entity_type": "station_queue",
                "station_id": queue.station_id,
                "station": STATIONS[queue.station_id],
                "payload": event["payload"],
            }), file=sys.stdout, flush=True)

if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)
    main()