"""StrategicAirlift_D0: top-level coupled DEVS model for the strategic airlift scenario.

This coupled model is structural only: it instantiates and wires sub-models.
It performs no active state transitions and no OS I/O.
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

        # No boundary ports for this coupled model (locked contract).

        # Instantiate fixed components
        facility = Facility(
            name="facility",
            parent=self,
            duration=float(duration),
            pallet_interval=float(pallet_interval),
            pallet_expiration_time=float(pallet_expiration_time),
        )
        self.add_component(facility)

        queue = LoadingQueue(name="queue", parent=self)
        self.add_component(queue)

        coordinator = FleetCoordinator(name="coordinator", parent=self)
        self.add_component(coordinator)

        destination = Destination(name="destination", parent=self)
        self.add_component(destination)

        # Instantiate runtime-sized aircraft family
        if int(num_aircraft) < 1:
            raise ValueError("num_aircraft must be >= 1")
        self.aircraft: list[Aircraft] = []
        for aircraft_id in range(1, int(num_aircraft) + 1):
            ac = Aircraft(
                name=f"aircraft_{aircraft_id}",
                parent=self,
                aircraft_id=int(aircraft_id),
                flight_time=float(flight_time),
                unload_time=float(unload_time),
                return_time=float(return_time),
                maintenance_time=float(maintenance_time),
            )
            self.aircraft.append(ac)
            self.add_component(ac)

        # Couplings (per locked topology and child interfaces)

        # Facility -> LoadingQueue (pallet flow)
        self.add_coupling(facility.output["pallet_out"], queue.input["pallet_in"])

        # Aircraft -> FleetCoordinator (idle reports)
        for ac in self.aircraft:
            self.add_coupling(ac.output["idle_out"], coordinator.input["aircraft_idle_in"])

        # FleetCoordinator -> LoadingQueue (claim request / aircraft offer)
        self.add_coupling(coordinator.output["claim_request_out"], queue.input["claim_request_in"])

        # LoadingQueue -> FleetCoordinator (claimed pallet)
        self.add_coupling(queue.output["claimed_pallet_out"], coordinator.input["claimed_pallet_in"])

        # FleetCoordinator -> Aircraft family (assignment broadcast; aircraft filters by aircraft_id)
        for ac in self.aircraft:
            self.add_coupling(coordinator.output["assignment_out"], ac.input["assignment_in"])

        # Aircraft -> Destination (delivery completion)
        for ac in self.aircraft:
            self.add_coupling(ac.output["delivery_out"], destination.input["delivery_in"])