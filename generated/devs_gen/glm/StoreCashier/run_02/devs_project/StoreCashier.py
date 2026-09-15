from xdevs.models import Atomic, Coupled, Port

from .StoreCashier_libs.StoreProcess import StoreProcess


class StoreCashier(Coupled):
    """Root container for the simulation. Passes statistical configuration parameters to the child atomic model."""

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
        seed: int | None = None,
    ):
        super().__init__(name)
        self.parent = parent

        process = StoreProcess(
            name="process",
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