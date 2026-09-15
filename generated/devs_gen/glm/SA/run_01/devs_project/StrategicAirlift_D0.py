from xdevs.models import Atomic, Coupled, Port

from .StrategicAirlift_D0_libs.Facility import Facility
from .StrategicAirlift_D0_libs.LoadingQueue import LoadingQueue
from .StrategicAirlift_D0_libs.FleetCoordinator import FleetCoordinator
from .StrategicAirlift_D0_libs.Aircraft import Aircraft
from .StrategicAirlift_D0_libs.Destination import Destination


class StrategicAirlift_D0(Coupled):
    """Orchestrate the airfreight logistics simulation by instantiating and connecting the Facility, LoadingQueue, FleetCoordinator, a fleet of Aircraft, and Destination. Passes configuration parameters to children and manages the simulation structure."""

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
        loading_queue = LoadingQueue(
            name="LoadingQueue",
            parent=self,
        )
        self.add_component(loading_queue)

        # Instantiate FleetCoordinator
        fleet_coordinator = FleetCoordinator(
            name="FleetCoordinator",
            parent=self,
        )
        self.add_component(fleet_coordinator)

        # Instantiate Destination
        destination = Destination(
            name="Destination",
            parent=self,
        )
        self.add_component(destination)

        # Instantiate Aircraft fleet
        self.aircrafts = []
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
            self.aircrafts.append(aircraft)
            self.add_component(aircraft)

        # --- Couplings ---

        # Connect Facility.pallet_out to LoadingQueue.pallet_in
        self.add_coupling(
            facility.output["pallet_out"],
            loading_queue.input["pallet_in"],
        )

        # Connect LoadingQueue.pallet_available_out to FleetCoordinator.pallet_available_in
        self.add_coupling(
            loading_queue.output["pallet_available_out"],
            fleet_coordinator.input["pallet_available_in"],
        )

        # Connect FleetCoordinator.queue_request_out to LoadingQueue.request_in
        self.add_coupling(
            fleet_coordinator.output["queue_request_out"],
            loading_queue.input["request_in"],
        )

        # Connect LoadingQueue.pallet_claimed_out to FleetCoordinator.pallet_claimed_in
        self.add_coupling(
            loading_queue.output["pallet_claimed_out"],
            fleet_coordinator.input["pallet_claimed_in"],
        )

        # For every Aircraft instance, connect Aircraft.idle_out to FleetCoordinator.aircraft_idle_in
        for aircraft in self.aircrafts:
            self.add_coupling(
                aircraft.output["idle_out"],
                fleet_coordinator.input["aircraft_idle_in"],
            )

        # Connect FleetCoordinator.assignment_out to every Aircraft.assignment_in instance
        for aircraft in self.aircrafts:
            self.add_coupling(
                fleet_coordinator.output["assignment_out"],
                aircraft.input["assignment_in"],
            )

        # For every Aircraft instance, connect Aircraft.delivery_out to Destination.delivery_in
        for aircraft in self.aircrafts:
            self.add_coupling(
                aircraft.output["delivery_out"],
                destination.input["delivery_in"],
            )