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
STATIONS = {1: "Bayview", 2: "Carling", 3: "Carleton", 4: "Confed", 5: "Greenboro"}
DIRECTIONS = {0: "Southbound", 1: "Northbound"}
TRAIN_INTERVAL = 225  # seconds

class PassengerGenerator(Atomic):
    def __init__(self, name: str, parent: Coupled | None, station_id: int):
        super().__init__(name)
        self.parent = parent
        self.station_id = station_id
        self.passenger_num = 0
        self.add_out_port(Port("passenger_generated", "passenger_generator"))

    def initialize(self):
        self.passenger_num = 0
        self.hold_in("INIT", 0.5)

    def lambdaf(self):
        pass

    def deltint(self):
        interval_mean = 300  # 5 minutes in seconds
        interval_std = 300  # 5 minutes in seconds
        interval = max(60, min(540, interval_mean + random.gauss(0, interval_std)))
        interval = round(interval)
        self.passenger_num += 1
        origin = self.station_id
        destination = random.choice([i for i in STATIONS if i != origin])
        passenger_id = self.passenger_num * 100 + origin * 10 + destination
        self.output["passenger_generated"].add({
            "passenger_id": passenger_id,
            "passenger_num": self.passenger_num,
            "origin": origin,
            "destination": destination,
        })
        self.hold_in("WAIT", interval)

    def deltext(self, e):
        pass

    def exit(self):
        pass

class Train(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.direction = 0
        self.current_station_id = 1
        self.add_out_port(Port("train_arrival", "train"))

    def initialize(self):
        self.direction = 0
        self.current_station_id = 1
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.output["train_arrival"].add({
            "station_id": self.current_station_id,
            "station": STATIONS[self.current_station_id],
            "direction": self.direction,
        })
        if self.current_station_id == 1 and self.direction == 0:
            self.current_station_id = 2
        elif self.current_station_id == 5 and self.direction == 1:
            self.current_station_id = 1
            self.direction = 0
        elif self.direction == 0:
            self.current_station_id += 1
            self.direction = 1 if self.current_station_id == 5 else self.direction
        else:
            self.current_station_id -= 1
            self.direction = 0 if self.current_station_id == 1 else self.direction
        self.hold_in("MOVE", TRAIN_INTERVAL)

    def deltext(self, e):
        pass

    def exit(self):
        pass

class StationQueue(Atomic):
    def __init__(self, name: str, parent: Coupled | None, station_id: int):
        super().__init__(name)
        self.parent = parent
        self.station_id = station_id
        self.queue = deque()
        self.add_in_port(Port("passenger_generated", "passenger_generator"))
        self.add_in_port(Port("train_arrival", "train"))
        self.add_out_port(Port("passenger_boarding", "station_queue"))

    def initialize(self):
        self.queue = deque()

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        if e[0] == "passenger_generated":
            passenger_data = e[0].value
            if passenger_data["origin"] == self.station_id:
                self.queue.append(passenger_data)
        elif e[0] == "train_arrival":
            train_data = e[0].value
            if train_data["station_id"] == self.station_id:
                while self.queue:
                    passenger_data = self.queue.popleft()
                    self.output["passenger_boarding"].add({
                        "passenger_id": passenger_data["passenger_id"],
                        "passenger_num": passenger_data["passenger_num"],
                        "origin": passenger_data["origin"],
                        "destination": passenger_data["destination"],
                    })
                    time.sleep(0.025)

    def exit(self):
        pass

class TrainQueue(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.passengers = []
        self.add_in_port(Port("passenger_boarding", "station_queue"))
        self.add_out_port(Port("passenger_exiting", "train_queue"))

    def initialize(self):
        self.passengers = []

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        if e[0] == "passenger_boarding":
            passenger_data = e[0].value
            self.passengers.append(passenger_data)

    def exit(self):
        for passenger_data in self.passengers:
            self.output["passenger_exiting"].add({
                "passenger_id": passenger_data["passenger_id"],
                "passenger_num": passenger_data["passenger_num"],
                "origin": passenger_data["origin"],
                "destination": passenger_data["destination"],
            })

class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.train = Train(name="train", parent=self)
        self.add_component(self.train)

        self.passenger_generators = []
        self.station_queues = []
        self.train_queue = TrainQueue(name="train_queue", parent=self)
        self.add_component(self.train_queue)

        for i in range(1, 6):
            passenger_generator = PassengerGenerator(name=f"passenger_generator_{i}", parent=self, station_id=i)
            self.add_component(passenger_generator)
            self.passenger_generators.append(passenger_generator)

            station_queue = StationQueue(name=f"station_queue_{i}", parent=self, station_id=i)
            self.add_component(station_queue)
            self.station_queues.append(station_queue)

        self.add_coupling(self.train.output["train_arrival"], self.station_queues[0].input["train_arrival"])
        self.add_coupling(self.train.output["train_arrival"], self.station_queues[1].input["train_arrival"])
        self.add_coupling(self.train.output["train_arrival"], self.station_queues[2].input["train_arrival"])
        self.add_coupling(self.train.output["train_arrival"], self.station_queues[3].input["train_arrival"])
        self.add_coupling(self.train.output["train_arrival"], self.station_queues[4].input["train_arrival"])

        self.add_coupling(self.passenger_generators[0].output["passenger_generated"], self.station_queues[0].input["passenger_generated"])
        self.add_coupling(self.passenger_generators[1].output["passenger_generated"], self.station_queues[1].input["passenger_generated"])
        self.add_coupling(self.passenger_generators[2].output["passenger_generated"], self.station_queues[2].input["passenger_generated"])
        self.add_coupling(self.passenger_generators[3].output["passenger_generated"], self.station_queues[3].input["passenger_generated"])
        self.add_coupling(self.passenger_generators[4].output["passenger_generated"], self.station_queues[4].input["passenger_generated"])

        self.add_coupling(self.station_queues[0].output["passenger_boarding"], self.train_queue.input["passenger_boarding"])
        self.add_coupling(self.station_queues[1].output["passenger_boarding"], self.train_queue.input["passenger_boarding"])
        self.add_coupling(self.station_queues[2].output["passenger_boarding"], self.train_queue.input["passenger_boarding"])
        self.add_coupling(self.station_queues[3].output["passenger_boarding"], self.train_queue.input["passenger_boarding"])
        self.add_coupling(self.station_queues[4].output["passenger_boarding"], self.train_queue.input["passenger_boarding"])

        self.add_coupling(self.train_queue.output["passenger_exiting"], self.output["passenger_exiting"])

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

    # Print final state
    print(json.dumps({"time": simulate_time, "event": "simulation_end"}), file=sys.stdout, flush=True)

if __name__ == "__main__":
    main()