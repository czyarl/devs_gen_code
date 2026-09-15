from xdevs.models import Atomic, Coupled, Port

from .StoreCashier_libs.StoreProcess import StoreProcess


class StoreCashier(Coupled):
    """Root coupled model acting as a container for the simulation. It initializes the single atomic child StoreProcess with all scenario configuration parameters derived from command-line arguments. It has no DEVS ports as the child manages all logic and output internally."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulation_time: str,
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

        process = StoreProcess(
            name="StoreProcess",
            parent=self,
            simulation_time=simulation_time,
            client_mean=client_mean,
            client_stddev=client_stddev,
            employee_1_mean=employee_1_mean,
            employee_1_stddev=employee_1_stddev,
            employee_2_mean=employee_2_mean,
            employee_2_stddev=employee_2_stddev,
            seed=seed,
        )
        self.add_component(process)