from xdevs.models import Atomic, Coupled, Port

from .Barbershop_D1_libs.CustomerSource import CustomerSource
from .Barbershop_D1_libs.Reception import Reception
from .Barbershop_D1_libs.CheckHair import CheckHair
from .Barbershop_D1_libs.CutHair import CutHair


class Barbershop_D1(Coupled):
    """Orchestrates the barbershop simulation by coupling the customer source, reception desk, hair inspection, and hair cutting components."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Instantiate children with configuration constants from requirements
        source = CustomerSource(name="source", parent=self)
        
        reception = Reception(
            name="reception",
            parent=self,
            queue_capacity=8,
            processing_time=5.0
        )
        
        checkhair = CheckHair(
            name="checkhair",
            parent=self,
            inspection_time=7.0
        )
        
        cuthair = CutHair(
            name="cuthair",
            parent=self,
            cutting_time=20.0
        )

        # Register components
        self.add_component(source)
        self.add_component(reception)
        self.add_component(checkhair)
        self.add_component(cuthair)

        # Define internal couplings
        self.add_coupling(source.output["out"], reception.input["in_cust"])
        self.add_coupling(reception.output["cust"], checkhair.input["in_cust"])
        self.add_coupling(checkhair.output["to_cut"], cuthair.input["in_cust"])
        self.add_coupling(cuthair.output["out"], checkhair.input["done_in"])
        self.add_coupling(checkhair.output["to_reception"], reception.input["done_in"])