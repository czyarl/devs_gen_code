from xdevs.models import Atomic, Coupled, Port
from .StrategicAirlift_D0_libs.Facility import Facility
from .StrategicAirlift_D0_libs.LoadingQueue import LoadingQueue
from .StrategicAirlift_D0_libs.FleetCoordinator import FleetCoordinator
from .StrategicAirlift_D0_libs.Aircraft import Aircraft
from .StrategicAirlift_D0_libs.Destination import Destination


class StrategicAirlift_D0(Coupled):
    """Top-level coupled model for simulating an airfreight logistics system."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        duration: float,
        num_aircraft: int,
        pallet_interval: float,
        pallet_expiration_time: float,
        flight_time: float,
        unload_time: float,
        return_time: float,
        maintenance_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        self.facility = Facility(
            name="facility",
            parent=self,
            pallet_interval=pallet_interval,
            pallet_expiration_time=pallet_expiration_time,
        )
        self.add_component(self.facility)

        self.loading_queue = LoadingQueue(
            name="loading_queue",
            parent=self,
            pallet_expiration_time=pallet_expiration_time,
        )
        self.add_component(self.loading_queue)

        self.fleet_coordinator = FleetCoordinator(
            name="fleet_coordinator",
            parent=self,
            num_aircraft=num_aircraft,
        )
        self.add_component(self.fleet_coordinator)

        self.aircrafts = []
        for index in range(num_aircraft):
            aircraft = Aircraft(
                name=f"aircraft_{index}",
                parent=self,
                flight_time=flight_time,
                unload_time=unload_time,
                return_time=return_time,
                maintenance_time=maintenance_time,
            )
            self.aircrafts.append(aircraft)
            self.add_component(aircraft)

        self.destination = Destination(
            name="destination",
            parent=self,
        )
        self.add_component(self.destination)

        self.add_coupling(
            self.facility.output["pallet_generated"],
            self.loading_queue.input["pallet_arrived"],
        )
        self.add_coupling(
            self.loading_queue.output["pallet_queued"],
            self.fleet_coordinator.input["pallet_queued"],
        )
        self.add_coupling(
            self.loading_queue.output["pallet_expired"],
            self.loading_queue.input["pallet_expired"],
        )
        self.add_coupling(
            self.fleet_coordinator.output["assignment_created"],
            self.aircrafts[0].input["assignment_arrived"],
        )
        for aircraft in self.aircrafts:
            self.add_coupling(
                aircraft.output["depart"],
                self.destination.input["pallet_delivered"],
            )
            self.add_coupling(
                aircraft.output["pallet_delivered"],
                self.destination.input["pallet_delivered"],
            )