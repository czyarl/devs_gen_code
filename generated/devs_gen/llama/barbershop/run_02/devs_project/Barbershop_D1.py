"""Complete pattern: a portless coupled root with one internal connection."""

from xdevs.models import Atomic, Coupled, Port
import sys
import json

from .Barbershop_D1_libs.ReceptionDesk import ReceptionDesk
from .Barbershop_D1_libs.HairInspectionPhase import HairInspectionPhase
from .Barbershop_D1_libs.HairCuttingPhase import HairCuttingPhase


class Barbershop_D1(Coupled):
    """Connect two children without inventing coupled boundary ports."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulation_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        reception_desk = ReceptionDesk(
            name="reception",
            parent=self,
        )
        hair_inspection_phase = HairInspectionPhase(
            name="hair_inspection",
            parent=self,
        )
        hair_cutting_phase = HairCuttingPhase(
            name="hair_cutting",
            parent=self,
        )
        self.add_component(reception_desk)
        self.add_component(hair_inspection_phase)
        self.add_component(hair_cutting_phase)

        self.add_coupling(
            reception_desk.output["cust"],
            hair_inspection_phase.input["cust"],
        )
        self.add_coupling(
            hair_inspection_phase.output["to_cut"],
            hair_cutting_phase.input["cust"],
        )
        self.add_coupling(
            hair_cutting_phase.output["out"],
            hair_inspection_phase.input["queue_status"],
        )
        self.add_coupling(
            hair_inspection_phase.output["to_reception"],
            reception_desk.input["queue_status"],
        )