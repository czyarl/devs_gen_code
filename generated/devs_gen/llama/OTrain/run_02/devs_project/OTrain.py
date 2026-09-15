"""Complete pattern: a coupled model with external IO."""

from xdevs.models import Atomic, Coupled, Port
from xdevs.models import get_current_time

from .OTrain_libs.TrainScheduler import TrainScheduler
from .OTrain_libs.StationManager import StationManager
from .OTrain_libs.PassengerGenerator import PassengerGenerator
from .OTrain_libs.OutputCollector import OutputCollector


class OTrain(Coupled):
    """Top-level coupled model. Routes events through the train and station systems."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.train_scheduler = TrainScheduler(
            name="train_scheduler",
            parent=self,
        )
        self.station_manager = StationManager(
            name="station_manager",
            parent=self,
        )
        self.passenger_generator = PassengerGenerator(
            name="passenger_generator",
            parent=self,
        )
        self.output_collector = OutputCollector(
            name="output_collector",
            parent=self,
        )
        self.add_component(self.train_scheduler)
        self.add_component(self.station_manager)
        self.add_component(self.passenger_generator)
        self.add_component(self.output_collector)

        self.add_coupling(
            self.train_scheduler.output["train_arrival"],
            self.station_manager.input["train_arrival"],
        )
        self.add_coupling(
            self.train_scheduler.output["train_arrival"],
            self.output_collector.input["train_arrival"],
        )
        self.add_coupling(
            self.passenger_generator.output["passenger_generated"],
            self.station_manager.input["passenger_generated"],
        )
        self.add_coupling(
            self.passenger_generator.output["passenger_generated"],
            self.output_collector.input["passenger_generated"],
        )
        self.add_coupling(
            self.station_manager.output["passenger_boarding"],
            self.output_collector.input["passenger_boarding"],
        )
        self.add_coupling(
            self.station_manager.output["passenger_exiting"],
            self.output_collector.input["passenger_exiting"],
        )