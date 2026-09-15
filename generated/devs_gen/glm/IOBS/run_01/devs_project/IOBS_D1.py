from xdevs.models import Atomic, Coupled, Port

from .IOBS_D1_libs.InputReader1 import InputReader1
from .IOBS_D1_libs.AAM1 import AAM1
from .IOBS_D1_libs.ANV1 import ANV1
from .IOBS_D1_libs.PV1 import PV1
from .IOBS_D1_libs.BPM1 import BPM1
from .IOBS_D1_libs.TPM1 import TPM1


class IOBS_D1(Coupled):
    """Coupled DEVS model for the Internet Online Banking System simulation."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Instantiate atomic components
        input_reader1 = InputReader1(name="input_reader1", parent=self)
        aam1 = AAM1(name="AAM1", parent=self)
        anv1 = ANV1(name="ANV1", parent=self)
        pv1 = PV1(name="PV1", parent=self)
        bpm1 = BPM1(name="BPM1", parent=self)
        tpm1 = TPM1(name="TPM1", parent=self)

        # Register components
        self.add_component(input_reader1)
        self.add_component(aam1)
        self.add_component(anv1)
        self.add_component(pv1)
        self.add_component(bpm1)
        self.add_component(tpm1)

        # Define internal couplings
        # Connect InputReader1.request_out to AAM1.request_in
        self.add_coupling(
            input_reader1.output["request_out"],
            aam1.input["request_in"]
        )

        # Connect AAM1.account_out to ANV1.account_in
        self.add_coupling(
            aam1.output["account_out"],
            anv1.input["account_in"]
        )

        # Connect ANV1.verification_out to PV1.verification_in
        self.add_coupling(
            anv1.output["verification_out"],
            pv1.input["verification_in"]
        )

        # Connect PV1.password_success_out to BPM1.password_success_in
        self.add_coupling(
            pv1.output["password_success_out"],
            bpm1.input["password_success_in"]
        )

        # Connect BPM1.bill_out to TPM1.bill_in
        self.add_coupling(
            bpm1.output["bill_out"],
            tpm1.input["bill_in"]
        )