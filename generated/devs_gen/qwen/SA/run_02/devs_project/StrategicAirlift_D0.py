from xdevs.models import Atomic, Coupled, Port
from .StrategicAirlift_D0_libs.Facility import Facility
from .StrategicAirlift_D0_libs.LoadingQueue import LoadingQueue
from .StrategicAirlift_D0_libs.FleetCoordinator import FleetCoordinator
from .StrategicAirlift_D0_libs.Aircraft import Aircraft
from .StrategicAirlift_D0_libs.Destination import Destination


class StrategicAirlift_D0(Coupled):
    """Top-level coupled system that orchestrates the airfreight logistics simulation. Contains all major entities and manages their interactions."""

    def __init__(self, name: str, parent: Coupled | None, duration: float, num_aircraft: int, pallet_interval: float, pallet_expiration_time: float, flight_time: float, unload_time: float, return_time: float, maintenance_time: float):
        super().__init__(name)
        self.parent = parent

        # Instantiate Facility
        facility = Facility(
            name="facility",
            parent=self,
            pallet_interval=pallet_interval,
            duration=duration
        )
        self.add_component(facility)

        # Instantiate LoadingQueue
        loading_queue = LoadingQueue(
            name="loading_queue",
            parent=self
        )
        self.add_component(loading_queue)

        # Instantiate FleetCoordinator
        fleet_coordinator = FleetCoordinator(
            name="fleet_coordinator",
            parent=self
        )
        self.add_component(fleet_coordinator)

        # Instantiate Destination
        destination = Destination(
            name="destination",
            parent=self
        )
        self.add_component(destination)

        # Instantiate Aircraft components
        self.aircrafts = []
        for i in range(num_aircraft):
            aircraft = Aircraft(
                name=f"aircraft_{i+1}",
                parent=self,
                aircraft_id=i+1,
                flight_time=flight_time,
                unload_time=unload_time,
                return_time=return_time,
                maintenance_time=maintenance_time
            )
            self.aircrafts.append(aircraft)
            self.add_component(aircraft)

        # Coupling Facility.pallet_out to LoadingQueue.pallet_in
        self.add_coupling(
            facility.output["pallet_out"],
            loading_queue.input["pallet_in"]
        )

        # Coupling FleetCoordinator.aircraft_request_out to LoadingQueue.assignment_request_in
        self.add_coupling(
            fleet_coordinator.output["aircraft_request_out"],
            loading_queue.input["assignment_request_in"]
        )

        # Coupling LoadingQueue.pallet_claimed_out to FleetCoordinator.pallet_available_in
        self.add_coupling(
            loading_queue.output["pallet_claimed_out"],
            fleet_coordinator.input["pallet_available_in"]
        )

        # Coupling FleetCoordinator.assignment_out to Aircraft.assignment_in
        for aircraft in self.aircrafts:
            self.add_coupling(
                fleet_coordinator.output["assignment_out"],
                aircraft.input["assignment_in"]
            )

        # Coupling Aircraft.aircraft_idle_out to FleetCoordinator.aircraft_idle_in
        for aircraft in self.aircrafts:
            self.add_coupling(
                aircraft.output["aircraft_idle_out"],
                fleet_coordinator.input["aircraft_idle_in"]
            )

        # Coupling Aircraft.depart_out to Destination.delivery_in
        for aircraft in self.aircrafts:
            self.add_coupling(
                aircraft.output["depart_out"],
                destination.input["delivery_in"]
            )

        # Coupling Aircraft.return_out to FleetCoordinator.aircraft_idle_in
        for aircraft in self.aircrafts:
            self.add_coupling(
                aircraft.output["return_out"],
                fleet_coordinator.input["aircraft_idle_in"]
            )

        # Coupling Aircraft.maintenance_start_out to Destination.delivery_in
        for aircraft in self.aircrafts:
            self.add_coupling(
                aircraft.output["maintenance_start_out"],
                destination.input["delivery_in"]
            )

        # Coupling Aircraft.maintenance_end_out to FleetCoordinator.aircraft_idle_in
        for aircraft in self.aircrafts:
            self.add_coupling(
                aircraft.output["maintenance_end_out"],
                fleet_coordinator.input["aircraft_idle_in"]
            )