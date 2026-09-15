from xdevs.models import Atomic, Coupled, Port

from .StrategicAirlift_D0_libs.Facility import Facility
from .StrategicAirlift_D0_libs.LoadingQueue import LoadingQueue
from .StrategicAirlift_D0_libs.FleetCoordinator import FleetCoordinator
from .StrategicAirlift_D0_libs.Aircraft import Aircraft
from .StrategicAirlift_D0_libs.Destination import Destination


class StrategicAirlift_D0(Coupled):
    """
    Top-level coupled DEVS model that composes the Facility pallet source,
    LoadingQueue with active expiration, FleetCoordinator dispatcher, a
    runtime-sized family of Aircraft, and the Destination sink; routes all
    required inter-model handoffs for pallet generation, FIFO claiming,
    aircraft assignment, idle/availability reporting, and delivery completion.

    Structural container only: no state transitions and no OS I/O.
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

        # This coupled model has no boundary ports per locked contract.

        facility = Facility(
            name="facility",
            parent=self,
            duration=duration,
            pallet_interval=pallet_interval,
            pallet_expiration_time=pallet_expiration_time,
        )
        self.add_component(facility)

        loading_queue = LoadingQueue(name="loading_queue", parent=self)
        self.add_component(loading_queue)

        coordinator = FleetCoordinator(name="fleet_coordinator", parent=self)
        self.add_component(coordinator)

        destination = Destination(name="destination", parent=self)
        self.add_component(destination)

        # Facility -> LoadingQueue
        self.add_coupling(
            facility.output["pallet_out"],
            loading_queue.input["pallet_in"],
        )

        # LoadingQueue -> FleetCoordinator
        self.add_coupling(
            loading_queue.output["cargo_available_out"],
            coordinator.input["cargo_available_in"],
        )

        # FleetCoordinator -> LoadingQueue (claim handshake)
        self.add_coupling(
            coordinator.output["claim_out"],
            loading_queue.input["claim_in"],
        )
        self.add_coupling(
            loading_queue.output["claimed_out"],
            coordinator.input["claimed_in"],
        )

        # Runtime-sized Aircraft family and couplings
        self.aircraft: list[Aircraft] = []
        for aircraft_id in range(1, int(num_aircraft) + 1):
            aircraft = Aircraft(
                name=f"aircraft_{aircraft_id}",
                parent=self,
                aircraft_id=aircraft_id,
                flight_time=flight_time,
                unload_time=unload_time,
                return_time=return_time,
                maintenance_time=maintenance_time,
            )
            self.aircraft.append(aircraft)
            self.add_component(aircraft)

            # Aircraft -> FleetCoordinator (idle status)
            self.add_coupling(
                aircraft.output["idle_out"],
                coordinator.input["aircraft_idle_in"],
            )

            # FleetCoordinator -> Aircraft (broadcast-tagged assignment)
            self.add_coupling(
                coordinator.output["assignment_out"],
                aircraft.input["assignment_in"],
            )

            # Aircraft -> Destination (delivery completion)
            self.add_coupling(
                aircraft.output["delivered_out"],
                destination.input["delivery_in"],
            )