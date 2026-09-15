from xdevs.models import Atomic, Coupled, Port

from .StrategicAirlift_D0_libs.Facility import Facility
from .StrategicAirlift_D0_libs.LoadingQueue import LoadingQueue
from .StrategicAirlift_D0_libs.FleetCoordinator import FleetCoordinator
from .StrategicAirlift_D0_libs.Aircraft import Aircraft
from .StrategicAirlift_D0_libs.Destination import Destination


class StrategicAirlift_D0(Coupled):
    """Root model for airfreight logistics simulation. Orchestrates the flow of cargo from generation through queuing, assignment to aircraft, transport, and final delivery. Manages the lifecycle of multiple aircraft instances and enforces global simulation time constraints via configuration passed to children. No direct external I/O; all stdout/stderr operations are delegated to leaf atomic models."""

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

        # Instantiate Facility
        facility = Facility(
            name="Facility",
            parent=self,
            duration=duration,
            pallet_interval=pallet_interval,
            pallet_expiration_time=pallet_expiration_time,
        )
        self.add_component(facility)

        # Instantiate LoadingQueue
        loading_queue = LoadingQueue(name="LoadingQueue", parent=self)
        self.add_component(loading_queue)

        # Instantiate FleetCoordinator
        fleet_coordinator = FleetCoordinator(name="FleetCoordinator", parent=self)
        self.add_component(fleet_coordinator)

        # Instantiate Destination
        destination = Destination(name="Destination", parent=self)
        self.add_component(destination)

        # Instantiate Aircraft instances
        self.aircraft_instances = []
        for i in range(num_aircraft):
            aircraft_id = i + 1  # 1-based ID
            aircraft = Aircraft(
                name=f"Aircraft_{aircraft_id}",
                parent=self,
                aircraft_id=aircraft_id,
                flight_time=flight_time,
                unload_time=unload_time,
                return_time=return_time,
                maintenance_time=maintenance_time,
            )
            self.aircraft_instances.append(aircraft)
            self.add_component(aircraft)

        # Define Couplings

        # Connect Facility.pallet_out to LoadingQueue.pallet_in
        self.add_coupling(
            facility.output["pallet_out"],
            loading_queue.input["pallet_in"],
        )

        # Connect FleetCoordinator.request_out to LoadingQueue.request_in
        self.add_coupling(
            fleet_coordinator.output["request_out"],
            loading_queue.input["request_in"],
        )

        # Connect LoadingQueue.claim_out to FleetCoordinator.claim_in
        self.add_coupling(
            loading_queue.output["claim_out"],
            fleet_coordinator.input["claim_in"],
        )

        # Connect FleetCoordinator.assignment_out to every Aircraft.assignment_in
        for aircraft in self.aircraft_instances:
            self.add_coupling(
                fleet_coordinator.output["assignment_out"],
                aircraft.input["assignment_in"],
            )

        # Connect every Aircraft.idle_out to FleetCoordinator.idle_in
        for aircraft in self.aircraft_instances:
            self.add_coupling(
                aircraft.output["idle_out"],
                fleet_coordinator.input["idle_in"],
            )

        # Connect every Aircraft.delivery_out to Destination.delivery_in
        for aircraft in self.aircraft_instances:
            self.add_coupling(
                aircraft.output["delivery_out"],
                destination.input["delivery_in"],
            )