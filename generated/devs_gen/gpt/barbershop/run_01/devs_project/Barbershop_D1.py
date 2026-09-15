"""Barbershop_D1 coupled model: structural container wiring the barbershop pipeline."""

from xdevs.models import Atomic, Coupled, Port

from .Barbershop_D1_libs.ScheduleSource import ScheduleSource
from .Barbershop_D1_libs.Reception import Reception
from .Barbershop_D1_libs.Checkhair import Checkhair
from .Barbershop_D1_libs.Cuthair import Cuthair


class Barbershop_D1(Coupled):
    """
    Top-level coupled DEVS model for the barbershop scenario.

    Pure structural container:
    - ScheduleSource -> Reception -> Checkhair -> Cuthair
    - Completion feedback: Cuthair -> Checkhair -> Reception
    """

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
        checkhair = Checkhair(
            name="checkhair",
            parent=self,
            consult_time_s=checkhair_consult_time_s,
        )
        cuthair = Cuthair(
            name="cuthair",
            parent=self,
            cut_time_s=cuthair_cut_time_s,
        )

        self.add_component(schedule)
        self.add_component(reception)
        self.add_component(checkhair)
        self.add_component(cuthair)

        # Arrivals: ScheduleSource -> Reception
        self.add_coupling(
            schedule.output["newcust_out"],
            reception.input["arrival_in"],
        )

        # Availability feedback: Checkhair -> Reception
        self.add_coupling(
            checkhair.output["available_out"],
            reception.input["checkhair_available_in"],
        )

        # Handoff: Reception -> Checkhair
        self.add_coupling(
            reception.output["cust"],
            checkhair.input["cust_in"],
        )

        # Forward to cutting: Checkhair -> Cuthair
        self.add_coupling(
            checkhair.output["to_cut"],
            cuthair.input["to_cut_in"],
        )

        # Cutting done: Cuthair -> Checkhair
        self.add_coupling(
            cuthair.output["out"],
            checkhair.input["cut_done_in"],
        )

        # Service done notification: Checkhair -> Reception
        self.add_coupling(
            checkhair.output["to_reception"],
            reception.input["service_done_in"],
        )