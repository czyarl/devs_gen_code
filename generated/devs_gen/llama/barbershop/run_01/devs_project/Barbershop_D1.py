"""Complete pattern: a coupled model Barbershop_D1."""

from xdevs.models import Atomic, Coupled, Port
from .Barbershop_D1_libs.ReceptionDesk import ReceptionDesk
from .Barbershop_D1_libs.HairInspectionPhase import HairInspectionPhase
from .Barbershop_D1_libs.HairCuttingPhase import HairCuttingPhase


class Barbershop_D1(Coupled):
    """Top-level coupled model. Routes customers through the barbershop workflow."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulation_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        reception = ReceptionDesk(
            name="reception",
            parent=self,
        )
        inspection = HairInspectionPhase(
            name="checkhair",
            parent=self,
        )
        cutting = HairCuttingPhase(
            name="cuthair",
            parent=self,
        )
        self.add_component(reception)
        self.add_component(inspection)
        self.add_component(cutting)

        self.add_coupling(
            reception.output["cust"],
            inspection.input["to_cut"],
        )
        self.add_coupling(
            inspection.output["to_cut"],
            cutting.input["cut_in"],
        )
        self.add_coupling(
            cutting.output["out"],
            inspection.input["cut_done"],
        )
        self.add_coupling(
            inspection.output["to_reception"],
            reception.input["cust_in"],
        )