"""Complete Python file for the House_Heating_D1 coupled model."""

from xdevs.models import Atomic, Coupled, Port
import sys
import json
import argparse

from .House_Heating_D1_libs.OutdoorTempSource import OutdoorTempSource
from .House_Heating_D1_libs.HeatingController import HeatingController


class House_Heating_D1(Coupled):
    """Top-level coupled model. Routes inputs and outputs."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulation_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        outdoor_temp_source = OutdoorTempSource(
            name="outdoor_temp_source",
            parent=self,
            simulation_time=simulation_time,
        )
        heating_controller = HeatingController(
            name="heating_controller",
            parent=self,
        )
        self.add_component(outdoor_temp_source)
        self.add_component(heating_controller)

        self.add_coupling(
            outdoor_temp_source.output["temperature_out"],
            heating_controller.input["temperature_in"],
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate_time", type=float, required=True)
    args = parser.parse_args()

    house_heating_d1 = House_Heating_D1(
        name="house_heating_d1",
        parent=None,
        simulation_time=args.simulate_time,
    )

    # Perform some initialization or simulation if needed
    # For this example, we just need to ensure the model can be instantiated

if __name__ == "__main__":
    main()