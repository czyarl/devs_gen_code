"""Complete pattern: a coupled container for employees."""

from xdevs.models import Atomic, Coupled, Port

from .Employees_libs.Employee1 import Employee1
from .Employees_libs.Employee2 import Employee2


class Employees(Coupled):
    """A coupled model containing multiple employee instances."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        employee_1_mean: float,
        employee_1_stddev: float,
        employee_2_mean: float,
        employee_2_stddev: float,
    ):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "employee_available_in"))
        self.add_out_port(Port(dict, "employee_available_out"))

        employee1 = Employee1(
            name="Employee1",
            parent=self,
            mean=employee_1_mean,
            stddev=employee_1_stddev,
        )
        employee2 = Employee2(
            name="Employee2",
            parent=self,
            mean=employee_2_mean,
            stddev=employee_2_stddev,
        )
        self.add_component(employee1)
        self.add_component(employee2)

        self.add_coupling(self.input["employee_available_in"], employee1.input["employee_available_in"])
        self.add_coupling(self.input["employee_available_in"], employee2.input["employee_available_in"])
        self.add_coupling(employee1.output["employee_available_out"], self.output["employee_available_out"])
        self.add_coupling(employee2.output["employee_available_out"], self.output["employee_available_out"])