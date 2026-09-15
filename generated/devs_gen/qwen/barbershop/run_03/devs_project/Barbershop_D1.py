"""Barbershop_D1: Coupled DEVS model coordinating the barbershop workflow."""

from xdevs.models import Atomic, Coupled, Port

from .Barbershop_D1_libs.EventSource import EventSource
from .Barbershop_D1_libs.ReceptionDesk import ReceptionDesk
from .Barbershop_D1_libs.HairInspectionPhase import HairInspectionPhase
from .Barbershop_D1_libs.HairCuttingPhase import HairCuttingPhase


class Barbershop_D1(Coupled):
    """Coordinates the barbershop workflow by routing customers through the reception, inspection, and cutting phases."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulation_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Create child components
        event_source = EventSource(name="EventSource", parent=self)
        reception = ReceptionDesk(
            name="ReceptionDesk",
            parent=self,
            queue_capacity=8,
            checkin_duration=5.0,
        )
        inspection = HairInspectionPhase(
            name="HairInspectionPhase",
            parent=self,
            inspection_duration=7.0,
        )
        cutting = HairCuttingPhase(
            name="HairCuttingPhase",
            parent=self,
            cutting_duration=20.0,
        )

        # Register components
        self.add_component(event_source)
        self.add_component(reception)
        self.add_component(inspection)
        self.add_component(cutting)

        # Define couplings
        self.add_coupling(
            event_source.output["newcust"],
            reception.input["newcust"],
        )
        self.add_coupling(
            reception.output["cust"],
            inspection.input["to_cut"],
        )
        self.add_coupling(
            inspection.output["to_cut"],
            cutting.input["in"],
        )
        self.add_coupling(
            cutting.output["out"],
            inspection.input["done"],
        )
        self.add_coupling(
            inspection.output["to_reception"],
            reception.input["done"],
        )