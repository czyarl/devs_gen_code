"""StoreCashier: Coupled DEVS model for simulating a store cashier system."""

from xdevs.models import Atomic, Coupled, Port
from .StoreCashier_libs.ClientGenerator import ClientGenerator
from .StoreCashier_libs.FIFOQueue import FIFOQueue
from .StoreCashier_libs.Employee1 import Employee1
from .StoreCashier_libs.Employee2 import Employee2


class StoreCashier(Coupled):
    """Coupled model for the store cashier system with one client generator,
    one FIFO queue, and two employees.
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulation_time: str = "00:05:00:000",
        client_mean: float = 10.0,
        client_stddev: float = 5.0,
        employee_1_mean: float = 20.0,
        employee_1_stddev: float = 0.0,
        employee_2_mean: float = 30.0,
        employee_2_stddev: float = 4.0,
    ):
        super().__init__(name)
        self.parent = parent

        # Instantiate components
        client_generator = ClientGenerator(
            name="ClientGenerator",
            parent=self,
            client_mean=client_mean,
            client_stddev=client_stddev,
        )
        fifo_queue = FIFOQueue(
            name="FIFOQueue",
            parent=self,
        )
        employee_1 = Employee1(
            name="Employee1",
            parent=self,
            employee_mean=employee_1_mean,
            employee_stddev=employee_1_stddev,
        )
        employee_2 = Employee2(
            name="Employee2",
            parent=self,
            employee_mean=employee_2_mean,
            employee_stddev=employee_2_stddev,
        )

        # Register components
        self.add_component(client_generator)
        self.add_component(fifo_queue)
        self.add_component(employee_1)
        self.add_component(employee_2)

        # Define couplings
        self.add_coupling(
            client_generator.output["client_out"],
            fifo_queue.input["client_in"],
        )
        self.add_coupling(
            fifo_queue.output["to_employee_1"],
            employee_1.input["client_in"],
        )
        self.add_coupling(
            fifo_queue.output["to_employee_2"],
            employee_2.input["client_in"],
        )
        self.add_coupling(
            employee_1.output["available_out"],
            fifo_queue.input["employee_1_available"],
        )
        self.add_coupling(
            employee_2.output["available_out"],
            fifo_queue.input["employee_2_available"],
        )