"""OTrain: Coupled DEVS model for the Ottawa O-Train light rail system."""

from xdevs.models import Atomic, Coupled, Port
from .OTrain_libs.TrainScheduler import TrainScheduler
from .OTrain_libs.PassengerGenerator import PassengerGenerator
from .OTrain_libs.StationQueue import StationQueue
from .OTrain_libs.TrainQueue import TrainQueue
from .OTrain_libs.OutputCollector import OutputCollector


class OTrain(Coupled):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulate_time: str = "00:01:00:000",
    ):
        super().__init__(name)
        self.parent = parent

        train_scheduler = TrainScheduler(name="TrainScheduler", parent=self)
        passenger_generator = PassengerGenerator(name="PassengerGenerator", parent=self)
        station_queue = StationQueue(name="StationQueue", parent=self)
        train_queue = TrainQueue(name="TrainQueue", parent=self)
        output_collector = OutputCollector(name="OutputCollector", parent=self)

        self.add_component(train_scheduler)
        self.add_component(passenger_generator)
        self.add_component(station_queue)
        self.add_component(train_queue)
        self.add_component(output_collector)

        self.add_coupling(
            train_scheduler.output["train_arrival"],
            station_queue.input["train_arrival"],
        )
        self.add_coupling(
            train_scheduler.output["train_arrival"],
            train_queue.input["train_arrival"],
        )
        self.add_coupling(
            passenger_generator.output["passenger_generated"],
            station_queue.input["passenger_generated"],
        )
        self.add_coupling(
            station_queue.output["passenger_boarding"],
            train_queue.input["passenger_boarding"],
        )
        self.add_coupling(
            train_queue.output["passenger_exiting"],
            output_collector.input["passenger_exiting"],
        )