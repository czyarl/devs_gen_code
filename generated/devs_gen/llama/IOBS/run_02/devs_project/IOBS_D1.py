"""Top-level coupled model for the Internet Online Banking System (IOBS) simulation."""

import argparse
import json
import random
import sys
from xdevs.models import Atomic, Coupled, Port
from xdevs.models import get_current_time

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
        aam = AAM(name="AAM", parent=self)
        anv = ANV(name="ANV", parent=self)
        pv = PV(name="PV", parent=self)
        bpm = BPM(name="BPM", parent=self)
        tpm = TPM(name="TPM", parent=self)

        self.add_component(input_reader1)
        self.add_component(aam)
        self.add_component(anv)
        self.add_component(pv)
        self.add_component(bpm)
        self.add_component(tpm)

        self.add_coupling(input_reader1.output["request_out"], aam.input["request_in"])
        self.add_coupling(aam.output["valid_request_out"], anv.input["request_in"])
        self.add_coupling(aam.output["logout_out"], self.output["logout_out"])
        self.add_coupling(anv.output["pass_request_out"], pv.input["request_in"])
        self.add_coupling(pv.output["success_request_out"], bpm.input["request_in"])
        self.add_coupling(bpm.output["bill_out"], tpm.input["bill_in"])

    def external_io(self):
        print(json.dumps({"time": get_current_time(), "model": "input_reader1", "event": "start", "data": {}}), flush=True)
        for line in sys.stdin:
            try:
                data = line.strip().split()
                time_str = data[0]
                hours, minutes, seconds = time_str.split(":")
                milliseconds = seconds.split(":")[1]
                seconds = seconds.split(":")[0]
                time = float(f"{hours}:{minutes}:{seconds}.{milliseconds}")
                valid = int(data[1])
                invalid = int(data[2])
                print(json.dumps({"time": time, "model": "input_reader1", "event": "input", "data": {"valid": valid, "invalid": invalid}}), flush=True)
            except Exception as e:
                print(f"Error processing line: {e}", file=sys.stderr, flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=1000000.0)
    args = parser.parse_args()

    iobs_d1 = IOBS_D1(name="IOBS_D1", parent=None, simulation_time=args.simulation_time)
    iobs_d1.external_io()