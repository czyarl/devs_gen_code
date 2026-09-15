from xdevs.models import Atomic, Coupled, Port

from .StrategicAirlift_D0_libs.Facility import Facility
from .StrategicAirlift_D0_libs.LoadingQueue import LoadingQueue
from .StrategicAirlift_D0_libs.FleetCoordinator import FleetCoordinator
from .StrategicAirlift_D0_libs.Aircraft import Aircraft
from .StrategicAirlift_D0_libs.Destination import Destination


class StrategicAirlift_D0(Coupled):
    """
    Orchestrate the airfreight logistics simulation by coupling the cargo source,
    queue, fleet coordinator, aircraft fleet, and destination.
    """

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
        aircraft_list = []
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
            aircraft_list.append(aircraft)
            self.add_component(aircraft)

        # Define Couplings

        # Facility -> LoadingQueue
        self.add_coupling(
            facility.output["pallet_out"],
            loading_queue.input["pallet_in"],
        )

        # LoadingQueue -> FleetCoordinator
        self.add_coupling(
            loading_queue.output["pallet_available"],
            fleet_coordinator.input["pallet_available"],
        )

        # FleetCoordinator -> LoadingQueue
        self.add_coupling(
            fleet_coordinator.output["claim_out"],
            loading_queue.input["claim_in"],
        )

        # LoadingQueue -> FleetCoordinator
        self.add_coupling(
            loading_queue.output["claimed_out"],
            fleet_coordinator.input["claimed_in"],
        )

        # FleetCoordinator -> Aircraft (broadcast)
        # Connect coordinator assignment output to every aircraft's assignment input.
        # Aircraft logic will filter based on aircraft_id.
        for aircraft in aircraft_list:
            self.add_coupling(
                fleet_coordinator.output["assignment_out"],
                aircraft.input["assignment_in"],
            )

        # Aircraft -> FleetCoordinator
        # Connect every aircraft's idle output to coordinator's idle input.
        for aircraft in aircraft_list:
            self.add_coupling(
                aircraft.output["idle_out"],
                fleet_coordinator.input["idle_in"],
            )

        # Aircraft -> Destination
        # Connect every aircraft's delivery output to destination's delivery input.
        for aircraft in aircraft_list:
            self.add_coupling(
                aircraft.output["delivery_out"],
                destination.input["delivery_in"],
            )