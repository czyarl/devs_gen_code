"""Top-level coupled model for Internet Online Banking System (IOBS) simulation."""

import argparse
import json
import logging
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time

from .IOBS_D1_libs.InputReader import InputReader
from .IOBS_D1_libs.AAM import AAM
from .IOBS_D1_libs.ANV import ANV
from .IOBS_D1_libs.PV import PV
from .IOBS_D1_libs.BPM import BPM
from .IOBS_D1_libs.TPM import TPM


class IOBS_D1(Coupled):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulation_time: float = 1000000.0,
    ):
        super().__init__(name)
        self.parent = parent

        input_reader1 = InputReader(name="input_reader1", parent=self)
        AAM1 = AAM(name="AAM1", parent=self)
        ANV1 = ANV(name="ANV1", parent=self)
        PV1 = PV(name="PV1", parent=self)
        BPM1 = BPM(name="BPM1", parent=self)
        TPM1 = TPM(name="TPM1", parent=self)

        self.add_component(input_reader1)
        self.add_component(AAM1)
        self.add_component(ANV1)
        self.add_component(PV1)
        self.add_component(BPM1)
        self.add_component(TPM1)

        self.add_coupling(
            input_reader1.output["request_out"],
            AAM1.input["request_in"],
        )
        self.add_coupling(
            AAM1.output["valid_request_out"],
            ANV1.input["request_in"],
        )
        self.add_coupling(
            ANV1.output["verification_out"],
            PV1.input["verification_in"],
        )
        self.add_coupling(
            PV1.output["verification_out"],
            BPM1.input["verification_in"],
        )
        self.add_coupling(
            BPM1.output["bill_out"],
            TPM1.input["bill_in"],
        )

    def external_io(self):
        logging.info("Checking stdin for input...")
        if sys.stdin is not None:
            for line in sys.stdin:
                try:
                    line = line.strip()
                    if line:
                        parts = line.split()
                        if len(parts) == 3:
                            timestamp = self.parse_timestamp(parts[0])
                            valid = int(parts[1])
                            invalid = int(parts[2])
                            self.input_reader1.request_out.emit(
                                {"valid": valid, "invalid": invalid, "timestamp": timestamp}
                            )
                except Exception as e:
                    logging.error(f"Error processing input: {e}")

        print(json.dumps({"time": get_current_time(), "model": "input_reader1", "event": "start", "data": {}}), flush=True)

def main():
    parser = argparse.ArgumentParser(description="IOBS Simulation")
    parser.add_argument("--simulation_time", type=float, default=1000000.0, help="Total simulation time in seconds.")
    args = parser.parse_args()

    root = IOBS_D1(name="IOBS_D1", parent=None, simulation_time=args.simulation_time)
    # Run the simulation
    # ...

if __name__ == "__main__":
    main()