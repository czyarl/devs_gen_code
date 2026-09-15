from xdevs.models import Atomic, Coupled, Port

from .Barbershop_D1_libs.InputSource import InputSource
from .Barbershop_D1_libs.Reception import Reception
from .Barbershop_D1_libs.CheckHair import CheckHair
from .Barbershop_D1_libs.CutHair import CutHair


class Barbershop_D1(Coupled):
    """Orchestrate the barbershop simulation by managing the flow of customers from input through reception, inspection, and cutting phases. This root model initializes the components, routes messages between them according to the business logic, and ensures the simulation runs until the specified time or all work is complete."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulation_time: float = 1000000.0,
    ):
        super().__init__(name)
        self.parent = parent

        # Instantiate components
        input_source = InputSource(name="InputSource", parent=self)
        
        reception = Reception(
            name="Reception",
            parent=self,
            capacity=8,
            process_time=5.0,
        )
        
        checkhair = CheckHair(
            name="CheckHair",
            parent=self,
            process_time=7.0,
        )
        
        cuthair = CutHair(
            name="CutHair",
            parent=self,
            process_time=20.0,
        )

        # Register components
        self.add_component(input_source)
        self.add_component(reception)
        self.add_component(checkhair)
        self.add_component(cuthair)

        # Define couplings
        # Connect InputSource.cust_arrival to Reception.arrival_in
        self.add_coupling(
            input_source.output["cust_arrival"],
            reception.input["arrival_in"],
        )

        # Connect Reception.cust to CheckHair.cust_in
        self.add_coupling(
            reception.output["cust"],
            checkhair.input["cust_in"],
        )

        # Connect CheckHair.to_cut to CutHair.cust_in
        self.add_coupling(
            checkhair.output["to_cut"],
            cuthair.input["cust_in"],
        )

        # Connect CutHair.out to CheckHair.cut_done
        self.add_coupling(
            cuthair.output["out"],
            checkhair.input["cut_done"],
        )

        # Connect CheckHair.to_reception to Reception.service_done
        self.add_coupling(
            checkhair.output["to_reception"],
            reception.input["service_done"],
        )