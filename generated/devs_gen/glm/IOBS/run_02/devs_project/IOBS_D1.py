from xdevs.models import Atomic, Coupled, Port

from .IOBS_D1_libs.InputReader import InputReader
from .IOBS_D1_libs.AAM import AAM
from .IOBS_D1_libs.ANV import ANV
from .IOBS_D1_libs.PV import PV
from .IOBS_D1_libs.BPM import BPM
from .IOBS_D1_libs.TPM import TPM


class IOBS_D1(Coupled):
    """Orchestrate the Internet Online Banking System simulation pipeline."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Instantiate components
        input_reader1 = InputReader(name="input_reader1", parent=self)
        aam1 = AAM(name="AAM1", parent=self)
        anv1 = ANV(name="ANV1", parent=self)
        pv1 = PV(name="PV1", parent=self)
        bpm1 = BPM(name="BPM1", parent=self)
        tpm1 = TPM(name="TPM1", parent=self)

        # Register components
        self.add_component(input_reader1)
        self.add_component(aam1)
        self.add_component(anv1)
        self.add_component(pv1)
        self.add_component(bpm1)
        self.add_component(tpm1)

        # Define couplings
        # Connect InputReader.request_out to AAM.request_in
        self.add_coupling(
            input_reader1.output["request_out"],
            aam1.input["request_in"]
        )

        # Connect AAM.account_out to ANV.account_in
        self.add_coupling(
            aam1.output["account_out"],
            anv1.input["account_in"]
        )

        # Connect ANV.verification_out to PV.verification_in
        self.add_coupling(
            anv1.output["verification_out"],
            pv1.input["verification_in"]
        )

        # Connect PV.success_out to BPM.success_in
        self.add_coupling(
            pv1.output["success_out"],
            bpm1.input["success_in"]
        )

        # Connect BPM.bill_out to TPM.bill_in
        self.add_coupling(
            bpm1.output["bill_out"],
            tpm1.input["bill_in"]
        )