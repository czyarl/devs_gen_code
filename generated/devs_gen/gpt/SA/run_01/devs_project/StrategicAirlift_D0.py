"""
StrategicAirlift_D0: Top-level coupled DEVS model (pure structure).

Instantiates:
- Facility: generates pallets
- LoadingQueue: FIFO with expiration + claim interface
- FleetCoordinator: matches idle aircraft to queued pallets
- Aircraft family: executes flight cycle
- Destination: records deliveries

This coupled model performs no active behavior and no OS I/O.
"""

from xdevs.models import Atomic, Coupled, Port

from .StrategicAirlift_D0_libs.Facility import Facility
from .StrategicAirlift_D0_libs.LoadingQueue import LoadingQueue
from .StrategicAirlift_D0_libs.FleetCoordinator import FleetCoordinator
from .StrategicAirlift_D0_libs.Aircraft import Aircraft
from .StrategicAirlift_D0_libs.Destination import Destination


class StrategicAirlift_D0(Coupled):
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

        # Locked contract: no boundary ports
        # (Do not add any ports.)

        # Components
        facility = Facility(
            name="facility",
            parent=self,
            duration=duration,
            pallet_interval=pallet_interval,
            pallet_expiration_time=pallet_expiration_time,
        )
        self.add_component(facility)

        queue = LoadingQueue(name="queue", parent=self)
        self.add_component(queue)

        coordinator = FleetCoordinator(name="coordinator", parent=self)
        self.add_component(coordinator)

        destination = Destination(name="destination", parent=self)
        self.add_component(destination)

        # Couplings: Facility -> Queue
        self.add_coupling(facility.output["pallet_out"], queue.input["pallet_in"])

        # Couplings: Queue <-> Coordinator
        self.add_coupling(queue.output["cargo_available_out"], coordinator.input["cargo_available_in"])
        self.add_coupling(coordinator.output["claim_request_out"], queue.input["claim_request_in"])
        self.add_coupling(queue.output["claimed_pallet_out"], coordinator.input["claimed_pallet_in"])

        # Aircraft family
        self.aircraft = []
        if int(num_aircraft) < 1:
            # Contract says num_aircraft >= 1; keep deterministic structure.
            # If violated by caller, build none rather than inventing behavior.
            num_aircraft = 0

        for aircraft_id in range(1, int(num_aircraft) + 1):
            ac = Aircraft(
                name=f"aircraft_{aircraft_id}",
                parent=self,
                aircraft_id=aircraft_id,
                flight_time=flight_time,
                unload_time=unload_time,
                return_time=return_time,
                maintenance_time=maintenance_time,
            )
            self.aircraft.append(ac)
            self.add_component(ac)

            # Aircraft availability -> Coordinator
            self.add_coupling(ac.output["idle_out"], coordinator.input["aircraft_idle_in"])

            # Coordinator assignment broadcast -> each Aircraft
            self.add_coupling(coordinator.output["assignment_out"], ac.input["assignment_in"])

            # Delivery -> Destination
            self.add_coupling(ac.output["delivered_out"], destination.input["delivered_in"])