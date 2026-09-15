import argparse
import json
import logging
import sys
from collections import deque
from xdevs import Atomic, Coupled, Port, get_current_time

from .StrategicAirlift_D0_libs.Facility import Facility
from .StrategicAirlift_D0_libs.LoadingQueue import LoadingQueue
from .StrategicAirlift_D0_libs.FleetCoordinator import FleetCoordinator
from .StrategicAirlift_D0_libs.AircraftCoordinator import AircraftCoordinator
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

        self.duration = duration

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
        )
        self.add_component(self.fleet_coordinator)

        self.aircraft_coordinator = AircraftCoordinator(
            name="aircraft_coordinator",
            parent=self,
            num_aircraft=num_aircraft,
            flight_time=flight_time,
            unload_time=unload_time,
            return_time=return_time,
            maintenance_time=maintenance_time,
        )
        self.add_component(self.aircraft_coordinator)

        self.destination = Destination(
            name="destination",
            parent=self,
            unload_time=unload_time,
        )
        self.add_component(self.destination)

        self.add_coupling(
            self.facility.output["pallet_generated"],
            self.loading_queue.input["pallet_arrival"],
        )
        self.add_coupling(
            self.loading_queue.output["pallet_queued"],
            self.fleet_coordinator.input["pallet_queued"],
        )
        self.add_coupling(
            self.fleet_coordinator.output["assignment_created"],
            self.aircraft_coordinator.input["assignment_created"],
        )
        self.add_coupling(
            self.aircraft_coordinator.output["depart"],
            self.destination.input["pallet_delivered"],
        )

    def lambdaf(self) -> None:
        if self.facility.pallet_generated:
            print(
                json.dumps(
                    {
                        "time": get_current_time(),
                        "entity": "facility",
                        "event": "pallet_generated",
                        "payload": self.facility.pallet_generated,
                    }
                ),
                flush=True,
            )
            self.facility.pallet_generated = None

        if self.loading_queue.pallet_queued:
            print(
                json.dumps(
                    {
                        "time": get_current_time(),
                        "entity": "queue",
                        "event": "pallet_queued",
                        "payload": self.loading_queue.pallet_queued,
                    }
                ),
                flush=True,
            )
            self.loading_queue.pallet_queued = None

        if self.loading_queue.pallet_expired:
            print(
                json.dumps(
                    {
                        "time": get_current_time(),
                        "entity": "queue",
                        "event": "pallet_expired",
                        "payload": self.loading_queue.pallet_expired,
                    }
                ),
                flush=True,
            )
            self.loading_queue.pallet_expired = None

        if self.fleet_coordinator.assignment_created:
            print(
                json.dumps(
                    {
                        "time": get_current_time(),
                        "entity": "coordinator",
                        "event": "assignment_created",
                        "payload": self.fleet_coordinator.assignment_created,
                    }
                ),
                flush=True,
            )
            self.fleet_coordinator.assignment_created = None

        if self.aircraft_coordinator.depart:
            print(
                json.dumps(
                    {
                        "time": get_current_time(),
                        "entity": "aircraft",
                        "event": "depart",
                        "payload": self.aircraft_coordinator.depart,
                    }
                ),
                flush=True,
            )
            self.aircraft_coordinator.depart = None

        if self.aircraft_coordinator.returned:
            print(
                json.dumps(
                    {
                        "time": get_current_time(),
                        "entity": "aircraft",
                        "event": "return",
                        "payload": self.aircraft_coordinator.returned,
                    }
                ),
                flush=True,
            )
            self.aircraft_coordinator.returned = None

        if self.aircraft_coordinator.maintenance_start:
            print(
                json.dumps(
                    {
                        "time": get_current_time(),
                        "entity": "aircraft",
                        "event": "maintenance_start",
                        "payload": self.aircraft_coordinator.maintenance_start,
                    }
                ),
                flush=True,
            )
            self.aircraft_coordinator.maintenance_start = None

        if self.aircraft_coordinator.maintenance_end:
            print(
                json.dumps(
                    {
                        "time": get_current_time(),
                        "entity": "aircraft",
                        "event": "maintenance_end",
                        "payload": self.aircraft_coordinator.maintenance_end,
                    }
                ),
                flush=True,
            )
            self.aircraft_coordinator.maintenance_end = None

        if self.destination.pallet_delivered:
            print(
                json.dumps(
                    {
                        "time": get_current_time(),
                        "entity": "destination",
                        "event": "pallet_delivered",
                        "payload": self.destination.pallet_delivered,
                    }
                ),
                flush=True,
            )
            self.destination.pallet_delivered = None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=10000.0)
    parser.add_argument("--num_aircraft", type=int, default=2)
    parser.add_argument("--pallet_interval", type=float, default=25.0)
    parser.add_argument("--pallet_expiration_time", type=float, default=150.0)
    parser.add_argument("--flight_time", type=float, default=30.0)
    parser.add_argument("--unload_time", type=float, default=2.0)
    parser.add_argument("--return_time", type=float, default=30.0)
    parser.add_argument("--maintenance_time", type=float, default=10.0)
    args = parser.parse_args()

    coupled_model = StrategicAirlift_D0(
        name="StrategicAirlift_D0",
        parent=None,
        duration=args.duration,
        num_aircraft=args.num_aircraft,
        pallet_interval=args.pallet_interval,
        pallet_expiration_time=args.pallet_expiration_time,
        flight_time=args.flight_time,
        unload_time=args.unload_time,
        return_time=args.return_time,
        maintenance_time=args.maintenance_time,
    )
    coupled_model.initialize()
    coupled_model.run()
    coupled_model.exit()


if __name__ == "__main__":
    main()