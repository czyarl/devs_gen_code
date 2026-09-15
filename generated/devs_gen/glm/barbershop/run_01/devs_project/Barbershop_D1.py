from xdevs.models import Atomic, Coupled, Port

from .Barbershop_D1_libs.CustomerSource import CustomerSource
from .Barbershop_D1_libs.ReceptionDesk import ReceptionDesk
from .Barbershop_D1_libs.HairInspector import HairInspector
from .Barbershop_D1_libs.HairCutter import HairCutter


class Barbershop_D1(Coupled):
    """Encapsulates the barbershop simulation, coordinating the flow of customers from the source through reception, inspection, and cutting phases according to the specified business logic and timing."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Instantiate components
        customer_source = CustomerSource(name="CustomerSource", parent=self)
        reception_desk = ReceptionDesk(name="ReceptionDesk", parent=self, queue_capacity=8, process_time=5.0)
        hair_inspector = HairInspector(name="HairInspector", parent=self, process_time=7.0)
        hair_cutter = HairCutter(name="HairCutter", parent=self, process_time=20.0)

        # Register components
        self.add_component(customer_source)
        self.add_component(reception_desk)
        self.add_component(hair_inspector)
        self.add_component(hair_cutter)

        # Define couplings
        # Connect CustomerSource.cust to ReceptionDesk.cust
        self.add_coupling(customer_source.output["cust"], reception_desk.input["cust"])

        # Connect ReceptionDesk.cust to HairInspector.cust
        self.add_coupling(reception_desk.output["cust"], hair_inspector.input["cust"])

        # Connect HairInspector.to_cut to HairCutter.to_cut
        self.add_coupling(hair_inspector.output["to_cut"], hair_cutter.input["to_cut"])

        # Connect HairCutter.out to HairInspector.out
        self.add_coupling(hair_cutter.output["out"], hair_inspector.input["out"])

        # Connect HairInspector.to_reception to ReceptionDesk.to_reception
        self.add_coupling(hair_inspector.output["to_reception"], reception_desk.input["to_reception"])