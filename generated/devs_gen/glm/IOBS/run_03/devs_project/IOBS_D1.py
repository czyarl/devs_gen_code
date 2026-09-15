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
        input_reader = InputReader(name="input_reader1", parent=self)
        aam = AAM(name="AAM1", parent=self, processing_delay=10.0)
        anv = ANV(name="ANV1", parent=self, processing_delay=10.0)
        pv = PV(name="PV1", parent=self, processing_delay=10.0)
        bpm = BPM(name="BPM1", parent=self, processing_delay=10.0)
        tpm = TPM(name="TPM1", parent=self, initial_balance=3000, processing_delay=10.0)

        # Register components
        self.add_component(input_reader)
        self.add_component(aam)
        self.add_component(anv)
        self.add_component(pv)
        self.add_component(bpm)
        self.add_component(tpm)

        # Define couplings
        # Connect InputReader.request_out to AAM.request_in
        self.add_coupling(
            input_reader.output["request_out"],
            aam.input["request_in"]
        )

        # Connect AAM.account_out to ANV.account_in
        self.add_coupling(
            aam.output["account_out"],
            anv.input["account_in"]
        )

        # Connect ANV.verification_out to PV.verification_in
        self.add_coupling(
            anv.output["verification_out"],
            pv.input["verification_in"]
        )

        # Connect PV.success_out to BPM.success_in
        self.add_coupling(
            pv.output["success_out"],
            bpm.input["success_in"]
        )

        # Connect TPM.balance_out to BPM.balance_in
        self.add_coupling(
            tpm.output["balance_out"],
            bpm.input["balance_in"]
        )

        # Connect BPM.bill_out to TPM.bill_in
        self.add_coupling(
            bpm.output["bill_out"],
            tpm.input["bill_in"]
        )