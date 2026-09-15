"""StoreCashier coupled DEVS model (structural container).

Instantiates:
- ClientGenerator
- Queue
- Employee_1
- Employee_2

And wires them so that:
- generated clients go to the queue
- employee availability goes to the queue
- queue assignments are broadcast to both employees (employees filter by employee_id)
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

        # No boundary ports (locked contract).

        # Components
        client_generator = ClientGenerator(
            name="ClientGenerator",
            parent=self,
            client_mean=client_mean,
            client_stddev=client_stddev,
            seed=seed,
        )
        queue = Queue(
            name="Queue",
            parent=self,
        )
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

        # Couplings
        # ClientGenerator -> Queue
        self.add_coupling(
            client_generator.output["client_out"],
            queue.input["client_in"],
        )

        # Queue -> Employees (broadcast; employees filter by employee_id)
        self.add_coupling(
            queue.output["assignment_out"],
            employee_1.input["assignment_in"],
        )
        self.add_coupling(
            queue.output["assignment_out"],
            employee_2.input["assignment_in"],
        )

        # Employees -> Queue (availability)
        self.add_coupling(
            employee_1.output["available_out"],
            queue.input["employee_available_in"],
        )
        self.add_coupling(
            employee_2.output["available_out"],
            queue.input["employee_available_in"],
        )