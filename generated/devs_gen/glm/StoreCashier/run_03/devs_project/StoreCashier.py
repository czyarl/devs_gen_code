from xdevs.models import Atomic, Coupled, Port

from .StoreCashier_libs.CashierProcess import CashierProcess


class StoreCashier(Coupled):
    """Root container for the cashier simulation. It holds the CashierProcess atomic model which manages client generation, queuing, and employee service logic. This model passes CLI configuration parameters to its child and does not perform any external IO or active state transitions itself."""

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

        process = CashierProcess(
            name="CashierProcess",
            parent=self,
            client_mean=client_mean,
            client_stddev=client_stddev,
            employee_1_mean=employee_1_mean,
            employee_1_stddev=employee_1_stddev,
            employee_2_mean=employee_2_mean,
            employee_2_stddev=employee_2_stddev,
            seed=seed,
        )
        self.add_component(process)