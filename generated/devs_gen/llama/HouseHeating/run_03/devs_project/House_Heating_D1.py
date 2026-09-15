"""Complete pattern: a portless coupled root with one internal connection."""

from xdevs.models import Atomic, Coupled, Port
import sys
import json
from .House_Heating_D1_libs.OutdoorTemperatureSource import OutdoorTemperatureSource
from .House_Heating_D1_libs.HeatingProcess import HeatingProcess


class House_Heating_D1(Coupled):
    """Connect two children without inventing coupled boundary ports."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulation_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        outdoor_temperature_source = OutdoorTemperatureSource(
            name="outdoor_temperature_source",
            parent=self,
            simulation_time=simulation_time,
        )
        heating_process = HeatingProcess(
            name="heating_process",
            parent=self,
        )
        self.add_component(outdoor_temperature_source)
        self.add_component(heating_process)

        self.add_coupling(
            outdoor_temperature_source.output["outdoor_temperature"],
            heating_process.input["outdoor_temperature"],
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate_time", type=float, required=True)
    args = parser.parse_args()

    coupled_model = House_Heating_D1(
        name="house_heating",
        parent=None,
        simulation_time=args.simulate_time,
    )
    coupled_model.initialize()
    coupled_model.run()