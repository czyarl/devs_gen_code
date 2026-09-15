"""
Barbershop_D1: top-level coupled DEVS model wiring the barbershop workflow.

This coupled model is structural only: it instantiates child atomic models and
connects their ports. All timing, same-time ordering, stdin parsing, and JSONL
logging are implemented inside the atomic children.
"""

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
        reception_queue_capacity: int,
        reception_checkin_time_s: float,
        checkhair_consult_time_s: float,
        cuthair_cut_time_s: float,
    ):
        super().__init__(name)
        self.parent = parent

        # No boundary ports per locked contract.

        schedule = ScheduleSource(name="schedule", parent=self)
        reception = Reception(
            name="reception",
            parent=self,
            queue_capacity=reception_queue_capacity,
            checkin_time_s=reception_checkin_time_s,
        )
        checkhair = CheckHair(
            name="checkhair",
            parent=self,
            consult_time_s=checkhair_consult_time_s,
        )
        cuthair = CutHair(
            name="cuthair",
            parent=self,
            cut_time_s=cuthair_cut_time_s,
        )

        self.add_component(schedule)
        self.add_component(reception)
        self.add_component(checkhair)
        self.add_component(cuthair)

        # Couplings (per planned topology and child interface manifests)
        self.add_coupling(schedule.output["arrival_out"], reception.input["arrival_in"])
        self.add_coupling(reception.output["cust"], checkhair.input["cust_in"])
        self.add_coupling(checkhair.output["to_cut"], cuthair.input["in_cust"])
        self.add_coupling(cuthair.output["out"], checkhair.input["cut_done_in"])
        self.add_coupling(checkhair.output["to_reception"], reception.input["service_done_in"])
        self.add_coupling(checkhair.output["availability_out"], reception.input["checkhair_available_in"])