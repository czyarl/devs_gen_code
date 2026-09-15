import argparse
import json
import logging
import random
import sys
import time
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
        self.hold_in("WAIT", 0.5)

    def lambdaf(self):
        passenger_id = 0 if self.phase == "INIT" else self.passenger_num * 100 + self.station_id * 10 + random.randint(1, 5)
        while passenger_id // 100 == self.passenger_num:
            destination = random.randint(1, 5)
            if destination != self.station_id:
                passenger_id = self.passenger_num * 100 + self.station_id * 10 + destination
        self.output["out"].add({
            "passenger_id": passenger_id,
            "passenger_num": self.passenger_num,
            "origin": self.station_id,
            "destination": passenger_id % 10,
        })

    def deltint(self):
        mean = 300  # 5 minutes
        std = 300  # 5 minutes
        interval = max(60, min(540, int(random.gauss(mean, std))))
        self.passenger_num += 1
        self.hold_in("WAIT", interval)

    def deltext(self, e):
        pass

    def exit(self):
        pass

class Train(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.station_id = 1
        self.direction = 0
        self.add_out_port(Port("train_arrival", "out"))

    def initialize(self):
        self.hold_in("WAIT", 0)

    def lambdaf(self):
        self.output["out"].add({
            "station": self.station_id,
            "direction": self.direction,
        })

    def deltint(self):
        if self.station_id == 5 and self.direction == 0:
            self.station_id = 1
            self.direction = 1
        elif self.station_id == 1 and self.direction == 1:
            self.station_id = 5
            self.direction = 0
        else:
            stations = [2, 3, 4, 5] if self.direction == 0 else [4, 3, 2, 1]
            self.station_id = stations[stations.index(self.station_id) + 1] if stations.index(self.station_id) < len(stations) - 1 else stations[0]
        self.hold_in("WAIT", 225)

    def deltext(self, e):
        pass

    def exit(self):
        pass

class StationQueue(Atomic):
    def __init__(self, name: str, parent: Coupled | None, station_id: int):
        super().__init__(name)
        self.parent = parent
        self.station_id = station_id
        self.queue = []
        self.add_in_port(Port("passenger_generated", "in"))
        self.add_out_port(Port("passenger_boarding", "out"))

    def initialize(self):
        pass

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        for event in e:
            if event.port == "in":
                self.queue.append(event.value)

    def exit(self):
        pass

class TrainQueue(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.queue = []
        self.add_in_port(Port("passenger_boarding", "in"))
        self.add_out_port(Port("passenger_exiting", "out"))

    def initialize(self):
        pass

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        pass

    def exit(self):
        pass

class OTrainSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.train = Train(name="train", parent=self)
        self.add_component(self.train)

        self.passenger_generators = []
        for i in range(1, 6):
            generator = PassengerGenerator(name=f"passenger_generator_{i}", parent=self, station_id=i)
            self.add_component(generator)
            self.passenger_generators.append(generator)

        self.station_queues = []
        for i in range(1, 6):
            queue = StationQueue(name=f"station_queue_{i}", parent=self, station_id=i)
            self.add_component(queue)
            self.station_queues.append(queue)

        self.train_queue = TrainQueue(name="train_queue", parent=self)
        self.add_component(self.train_queue)

        # EIC
        # IC
        # EOC

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate_time", type=str, default="00:01:00:000")
    args = parser.parse_args()

    hours, minutes, seconds, milliseconds = map(int, args.simulate_time.split(':'))
    simulate_time = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000

    root = OTrainSystem(name="system", parent=None)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(simulate_time)

if __name__ == "__main__":
    random.seed(time.time_ns())
    logging.basicConfig(stream=sys.stderr)
    main()