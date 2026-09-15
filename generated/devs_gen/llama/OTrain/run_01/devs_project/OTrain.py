"""OTrain: Coupled DEVS model for simulating the Ottawa O-Train light rail system."""

from xdevs.models import Coupled, Port
from .OTrain_libs.TrainScheduler import TrainScheduler
from .OTrain_libs.PassengerGenerator import PassengerGenerator
from .OTrain_libs.StationQueue import StationQueue
from .OTrain_libs.TrainQueue import TrainQueue
from .OTrain_libs.ReportCollector import ReportCollector


class OTrain(Coupled):
    """Coupled DEVS model for the Ottawa O-Train light rail system."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulate_time: str = "00:01:00:000",
    ):
        super().__init__(name)
        self.parent = parent

        train_scheduler = TrainScheduler(
            name="train_scheduler",
            parent=self,
        )
        passenger_generator = PassengerGenerator(
            name="passenger_generator",
            parent=self,
        )
        station_queue_1 = StationQueue(
            name="station_queue_1",
            parent=self,
        )
        station_queue_2 = StationQueue(
            name="station_queue_2",
            parent=self,
        )
        station_queue_3 = StationQueue(
            name="station_queue_3",
            parent=self,
        )
        station_queue_4 = StationQueue(
            name="station_queue_4",
            parent=self,
        )
        station_queue_5 = StationQueue(
            name="station_queue_5",
            parent=self,
        )
        train_queue = TrainQueue(
            name="train_queue",
            parent=self,
        )
        report_collector = ReportCollector(
            name="report_collector",
            parent=self,
        )
        self.add_component(train_scheduler)
        self.add_component(passenger_generator)
        self.add_component(station_queue_1)
        self.add_component(station_queue_2)
        self.add_component(station_queue_3)
        self.add_component(station_queue_4)
        self.add_component(station_queue_5)
        self.add_component(train_queue)
        self.add_component(report_collector)

        self.add_coupling(
            train_scheduler.output["train_arrival"],
            station_queue_1.input["train_arrival"],
        )
        self.add_coupling(
            train_scheduler.output["train_arrival"],
            train_queue.input["train_arrival"],
        )
        self.add_coupling(
            passenger_generator.output["passenger_generated"],
            station_queue_1.input["passenger_generated"],
        )
        self.add_coupling(
            station_queue_1.output["passenger_boarding"],
            train_queue.input["passenger_boarding"],
        )
        self.add_coupling(
            train_queue.output["passenger_exiting"],
            station_queue_1.input["passenger_exiting"],
        )