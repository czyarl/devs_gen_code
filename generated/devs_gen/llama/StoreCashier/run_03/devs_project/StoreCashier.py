"""Complete implementation of the StoreCashier model."""

from xdevs.models import Atomic, Coupled, Port
from datetime import datetime, timedelta

from .StoreCashier_libs.ClientGenerator import ClientGenerator
from .StoreCashier_libs.Queue import Queue
from .StoreCashier_libs.Employees import Employees


class StoreCashier(Coupled):
    """Coupled model for a store cashier system."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        client_mean: float,
        client_stddev: float,
        employee_1_mean: float,
        employee_1_stddev: float,
        employee_2_mean: float,
        employee_2_stddev: float,
        simulation_time: str,
    ):
        super().__init__(name)
        self.parent = parent

        self.client_generator = ClientGenerator(
            name="ClientGenerator",
            parent=self,
            mean=client_mean,
            stddev=client_stddev,
        )
        self.queue = Queue(
            name="Queue",
            parent=self,
        )
        self.employees = Employees(
            name="Employees",
            parent=self,
            employee_1_mean=employee_1_mean,
            employee_1_stddev=employee_1_stddev,
            employee_2_mean=employee_2_mean,
            employee_2_stddev=employee_2_stddev,
        )

        self.add_component(self.client_generator)
        self.add_component(self.queue)
        self.add_component(self.employees)

        self.add_coupling(
            self.client_generator.output["client_out"],
            self.queue.input["client_in"],
        )
        self.add_coupling(
            self.employees.output["employee_available_out"],
            self.queue.input["employee_available_in"],
        )
        self.add_coupling(
            self.queue.output["to_employees"],
            self.employees.input["employee_available_in"],
        )

    def external_io(self):
        # Parse command-line arguments
        import argparse
        import re

        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--simulation_time",
            type=str,
            default="00:05:00:000",
            help="Simulation time in HH:MM:SS:mmm format",
        )
        parser.add_argument(
            "--client_mean",
            type=float,
            default=10.0,
            help="Client inter-arrival mean",
        )
        parser.add_argument(
            "--client_stddev",
            type=float,
            default=5.0,
            help="Client inter-arrival stddev",
        )
        parser.add_argument(
            "--employee_1_mean",
            type=float,
            default=20.0,
            help="Employee 1 service mean",
        )
        parser.add_argument(
            "--employee_1_stddev",
            type=float,
            default=0.0,
            help="Employee 1 service stddev",
        )
        parser.add_argument(
            "--employee_2_mean",
            type=float,
            default=30.0,
            help="Employee 2 service mean",
        )
        parser.add_argument(
            "--employee_2_stddev",
            type=float,
            default=4.0,
            help="Employee 2 service stddev",
        )
        args = parser.parse_args()

        # Convert simulation time to seconds
        time_parts = re.split(r":", args.simulation_time)
        simulation_time_seconds = (
            int(time_parts[0]) * 3600
            + int(time_parts[1]) * 60
            + int(time_parts[2])
            + int(time_parts[3]) / 1000
        )

        # Set simulation time and parameters
        self.client_mean = args.client_mean
        self.client_stddev = args.client_stddev
        self.employee_1_mean = args.employee_1_mean
        self.employee_1_stddev = args.employee_1_stddev
        self.employee_2_mean = args.employee_2_mean
        self.employee_2_stddev = args.employee_2_stddev

        # Initialize components with parsed parameters
        self.client_generator.mean = self.client_mean
        self.client_generator.stddev = self.client_stddev
        self.employees.employee_1_mean = self.employee_1_mean
        self.employees.employee_1_stddev = self.employee_1_stddev
        self.employees.employee_2_mean = self.employee_2_mean
        self.employees.employee_2_stddev = self.employee_2_stddev

        # Print simulation parameters and header
        print(
            json.dumps(
                {
                    "time": 0.0,
                    "time_str": "00:00:00:000",
                    "event": "simulation_start",
                    "entity_type": "root",
                    "entity": "StoreCashier",
                    "payload": {},
                }
            ),
            flush=True,
        )
        print(
            json.dumps(
                {
                    "time": 0.0,
                    "time_str": "00:00:00:000",
                    "event": "client_generated",
                    "entity_type": "client_generator",
                    "entity": "ClientGenerator",
                    "payload": {
                        "client_id": 1,
                        "arrival_time": 0.0,
                    },
                }
            ),
            flush=True,
        )
        print(
            json.dumps(
                {
                    "time": 0.0,
                    "time_str": "00:00:00:000",
                    "event": "employee_available",
                    "entity_type": "employee",
                    "entity": "Employee_1",
                    "payload": {
                        "employee_id": 1,
                    },
                }
            ),
            flush=True,
        )
        print(
            json.dumps(
                {
                    "time": 0.0,
                    "time_str": "00:00:00:000",
                    "event": "employee_available",
                    "entity_type": "employee",
                    "entity": "Employee_2",
                    "payload": {
                        "employee_id": 2,
                    },
                }
            ),
            flush=True,
        )

        # Run simulation
        import sys
        sim = self.model.simulate(
            simulation_time=simulation_time_seconds,
            q=q,
        )
        for t in sim:
            pass