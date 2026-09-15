from xdevs.models import Atomic, Coupled, Port
from .StrategicAirlift_D0_libs.Facility import Facility
from .StrategicAirlift_D0_libs.LoadingQueue import LoadingQueue
from .StrategicAirlift_D0_libs.FleetCoordinator import FleetCoordinator
from .StrategicAirlift_D0_libs.Aircraft import Aircraft
from .StrategicAirlift_D0_libs.Destination import Destination


class StrategicAirlift_D0(Coupled):
    def __init__(self, name: str, parent: Coupled | None, duration: float, num_aircraft: int, pallet_interval: float, pallet_expiration_time: float, flight_time: float, unload_time: float, return_time: float, maintenance_time: float):
        super().__init__(name)
        self.parent = parent

        # Instantiate components
        facility = Facility(
            name="facility",
            parent=self,
            pallet_interval=pallet_interval,
            pallet_expiration_time=pallet_expiration_time,
            duration=duration
        )
        self.add_component(facility)

        loading_queue = LoadingQueue(
            name="loading_queue",
            parent=self,
            pallet_expiration_time=pallet_expiration_time
        )
        self.add_component(loading_queue)

        coordinator = FleetCoordinator(
            name="fleet_coordinator",
            parent=self
        )
        self.add_component(coordinator)

        aircrafts = []
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
            aircrafts.append(aircraft)
            self.add_component(aircraft)

        destination = Destination(
            name="destination",
            parent=self
        )
        self.add_component(destination)

        # Define couplings
        self.add_coupling(facility.output["pallet_out"], loading_queue.input["pallet_in"])

        for aircraft in aircrafts:
            self.add_coupling(aircraft.output["available_out"], coordinator.input["available_in"])

        self.add_coupling(coordinator.output["claim_out"], loading_queue.input["claim_in"])
        self.add_coupling(loading_queue.output["claimed_out"], coordinator.input["claimed_in"])

        for aircraft in aircrafts:
            self.add_coupling(coordinator.output["assignment_out"], aircraft.input["assignment_in"])

        for aircraft in aircrafts:
            self.add_coupling(aircraft.output["delivery_out"], destination.input["delivery_in"])