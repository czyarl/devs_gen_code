"""Complete pattern: a portless coupled root with one internal connection."""

from xdevs.models import Atomic, Coupled, Port
import json
import sys
import argparse
from datetime import datetime
import time
import random
from typing import Dict

from .IOBS_D1_libs.input_reader1 import input_reader1
from .IOBS_D1_libs.AAM1 import AAM1
from .IOBS_D1_libs.ANV1 import ANV1
from .IOBS_D1_libs.PV1 import PV1
from .IOBS_D1_libs.BPM1 import BPM1
from .IOBS_D1_libs.TPM1 import TPM1


class IOBS_D1(Coupled):
    """Top-level coupled model for Internet Online Banking System (IOBS) simulation."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulation_time: float = 1000000.0,
    ):
        super().__init__(name)
        self.parent = parent

        input_reader1_1 = input_reader1(
            name="input_reader1",
            parent=self,
        )
        AAM1_1 = AAM1(
            name="AAM1",
            parent=self,
        )
        ANV1_1 = ANV1(
            name="ANV1",
            parent=self,
        )
        PV1_1 = PV1(
            name="PV1",
            parent=self,
        )
        BPM1_1 = BPM1(
            name="BPM1",
            parent=self,
        )
        TPM1_1 = TPM1(
            name="TPM1",
            parent=self,
        )

        self.add_component(input_reader1_1)
        self.add_component(AAM1_1)
        self.add_component(ANV1_1)
        self.add_component(PV1_1)
        self.add_component(BPM1_1)
        self.add_component(TPM1_1)

        self.add_coupling(
            input_reader1_1.output["AAM1_in"],
            AAM1_1.input["input"],
        )
        self.add_coupling(
            AAM1_1.output["ANV1_in"],
            ANV1_1.input["input"],
        )
        self.add_coupling(
            ANV1_1.output["PV1_in"],
            PV1_1.input["input"],
        )
        self.add_coupling(
            PV1_1.output["BPM1_in"],
            BPM1_1.input["input"],
        )
        self.add_coupling(
            BPM1_1.output["TPM1_in"],
            TPM1_1.input["input"],
        )

        self.external_io = [
            {"target": "stdout", "content": {"model": "IOBS_D1", "event": "start", "time": 0.0, "data": {}}}
        ]

    def lambdaf(self, event: str, port: str, data: Dict) -> None:
        current_time = self.get_current_time()
        if event == "start":
            print(json.dumps({"time": current_time, "model": "input_reader1", "event": "start", "data": {}}, flush=True))
        elif event == "input":
            print(json.dumps({"time": current_time, "model": "input_reader1", "event": "input", "data": data}, flush=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=1000000.0)
    args = parser.parse_args()

    random.seed(time.time_ns() % (2**32 - 1))

    coupled_model = IOBS_D1(
        name="IOBS_D1",
        parent=None,
        simulation_time=args.simulation_time,
    )
    coupled_model.initialize()
    coupled_model.run()