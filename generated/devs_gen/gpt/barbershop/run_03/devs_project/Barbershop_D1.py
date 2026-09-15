from xdevs.models import Atomic, Coupled, Port

from .Barbershop_D1_libs.ScheduleSource import ScheduleSource
from .Barbershop_D1_libs.Reception import Reception
from .Barbershop_D1_libs.CheckHair import CheckHair
from .Barbershop_D1_libs.CutHair import CutHair


class Barbershop_D1(Coupled):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        reception_capacity: int,
        reception_checkin_time_s: float,
        checkhair_consult_time_s: float,
        cuthair_cut_time_s: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Children
        source = ScheduleSource(name="source", parent=self)

        reception = Reception(
            name="reception",
            parent=self,
            capacity=int(reception_capacity),
            checkin_time_s=float(reception_checkin_time_s),
        )

        checkhair = CheckHair(
            name="checkhair",
            parent=self,
            consult_time_s=float(checkhair_consult_time_s),
        )

        cuthair = CutHair(
            name="cuthair",
            parent=self,
            cut_time_s=float(cuthair_cut_time_s),
        )

        self.add_component(source)
        self.add_component(reception)
        self.add_component(checkhair)
        self.add_component(cuthair)

        # Couplings (internal only; this coupled model has no boundary ports)
        self.add_coupling(
            source.output["newcust_out"],
            reception.input["arrival_in"],
        )
        self.add_coupling(
            reception.output["cust"],
            checkhair.input["cust_in"],
        )
        self.add_coupling(
            checkhair.output["to_cut"],
            cuthair.input["to_cut_in"],
        )
        self.add_coupling(
            cuthair.output["out"],
            checkhair.input["cut_done_in"],
        )
        self.add_coupling(
            checkhair.output["to_reception"],
            reception.input["barber_done_in"],
        )
        self.add_coupling(
            checkhair.output["available_out"],
            reception.input["checkhair_available_in"],
        )