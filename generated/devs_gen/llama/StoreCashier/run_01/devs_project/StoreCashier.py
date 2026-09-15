"""Complete implementation of the StoreCashier coupled model."""

from xdevs.models import Atomic, Coupled, Port
from xdevs.models import get_current_time

from .StoreCashier_libs.ClientGenerator import ClientGenerator
from .StoreCashier_libs.Queue import Queue
from .StoreCashier_libs.Employee1 import Employee1
from .StoreCashier_libs.Employee2 import Employee2


class StoreCashier(Coupled):
    """Simulate a store cashier system with one client generator, one FIFO queue, and two employees."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulation_time: str,
    ):
        super().__init__(name)
        self.parent = parent

        client_generator = ClientGenerator(
            name="ClientGenerator",
            parent=self,
            arrival_interval_mean=10.0,
            arrival_interval_stddev=5.0,
        )
        queue = Queue(
            name="Queue",
            parent=self,
        )
        employee_1 = Employee1(
            name="Employee1",
            parent=self,
            service_time_mean=20.0,
            service_time_stddev=0.0,
        )
        employee_2 = Employee2(
            name="Employee2",
            parent=self,
            service_time_mean=30.0,
            service_time_stddev=4.0,
        )

        self.add_component(client_generator)
        self.add_component(queue)
        self.add_component(employee_1)
        self.add_component(employee_2)

        self.add_in_port(Port(dict, ""))
        self.add_out_port(Port(dict, ""))

        self.add_coupling(
            client_generator.output["client_out"],
            queue.input["client_in"],
        )
        self.add_coupling(
            queue.output["to_employee_1"],
            employee_1.input["job_in"],
        )
        self.add_coupling(
            queue.output["to_employee_2"],
            employee_2.input["job_in"],
        )
        self.add_coupling(
            employee_1.output["available_out"],
            queue.input["employee_1_available"],
        )
        self.add_coupling(
            employee_2.output["available_out"],
            queue.input["employee_2_available"],
        )