"""StoreCashier coupled DEVS model: two-employee store cashier simulation.

Structural composition only: composes ClientGenerator, Queue, and two Employee
instances, and wires their ports according to the planned topology.
"""

from xdevs.models import Atomic, Coupled, Port

from .StoreCashier_libs.ClientGenerator import ClientGenerator
from .StoreCashier_libs.Queue import Queue
from .StoreCashier_libs.Employee import Employee


class StoreCashier(Coupled):
    """Top-level coupled model for the two-employee store cashier scenario."""

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
        seed: int,
    ):
        super().__init__(name)
        self.parent = parent

        # No boundary ports for this coupled model (children handle all IO/logging).

        client_generator = ClientGenerator(
            name="ClientGenerator",
            parent=self,
            client_mean=client_mean,
            client_stddev=client_stddev,
            seed=seed,
        )
        queue = Queue(name="Queue", parent=self)

        employee_1 = Employee(
            name="Employee_1",
            parent=self,
            employee_id=1,
            service_mean=employee_1_mean,
            service_stddev=employee_1_stddev,
            seed=seed,
        )
        employee_2 = Employee(
            name="Employee_2",
            parent=self,
            employee_id=2,
            service_mean=employee_2_mean,
            service_stddev=employee_2_stddev,
            seed=seed,
        )

        self.add_component(client_generator)
        self.add_component(queue)
        self.add_component(employee_1)
        self.add_component(employee_2)

        # ClientGenerator -> Queue
        self.add_coupling(
            client_generator.output["clients_out"],
            queue.input["client_in"],
        )

        # Queue -> Employees (broadcast; each employee filters by employee_id)
        self.add_coupling(
            queue.output["pairing_out"],
            employee_1.input["pairing_in"],
        )
        self.add_coupling(
            queue.output["pairing_out"],
            employee_2.input["pairing_in"],
        )

        # Employees -> Queue availability
        self.add_coupling(
            employee_1.output["available_out"],
            queue.input["employee_available_in"],
        )
        self.add_coupling(
            employee_2.output["available_out"],
            queue.input["employee_available_in"],
        )