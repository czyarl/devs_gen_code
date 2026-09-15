"""Barbershop_D1: Coupled DEVS model orchestrating the barbershop workflow."""

from xdevs.models import Atomic, Coupled, Port

from .Barbershop_D1_libs.CustomerSource import CustomerSource
from .Barbershop_D1_libs.ReceptionDesk import ReceptionDesk
from .Barbershop_D1_libs.HairInspection import HairInspection
from .Barbershop_D1_libs.HairCutting import HairCutting


class Barbershop_D1(Coupled):
    """Orchestrates the barbershop workflow by managing customer flow between the reception, inspection, and cutting phases."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulation_time: float = 1000000.0,
    ):
        super().__init__(name)
        self.parent = parent

        # Instantiate child components
        customer_source = CustomerSource(name="CustomerSource", parent=self)
        reception_desk = ReceptionDesk(
            name="ReceptionDesk",
            parent=self,
            queue_capacity=8,
            check_in_time=5.0,
        )
        hair_inspection = HairInspection(
            name="HairInspection",
            parent=self,
            consultation_time=7.0,
        )
        hair_cutting = HairCutting(
            name="HairCutting",
            parent=self,
            cutting_time=20.0,
        )

        # Register components
        self.add_component(customer_source)
        self.add_component(reception_desk)
        self.add_component(hair_inspection)
        self.add_component(hair_cutting)

        # Define couplings as per the locked contract
        self.add_coupling(
            customer_source.output["cust"],
            reception_desk.input["cust"],
        )
        self.add_coupling(
            reception_desk.output["cust"],
            hair_inspection.input["to_cut"],
        )
        self.add_coupling(
            hair_inspection.output["to_cut"],
            hair_cutting.input["to_cut"],
        )
        self.add_coupling(
            hair_cutting.output["out"],
            hair_inspection.input["to_reception"],
        )
        self.add_coupling(
            hair_inspection.output["to_reception"],
            reception_desk.input["cust"],
        )