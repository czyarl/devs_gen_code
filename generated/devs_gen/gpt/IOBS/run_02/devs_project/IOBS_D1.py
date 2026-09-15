"""
Top-level coupled DEVS model for the Internet Online Banking System (IOBS) pipeline.

This coupled model is a pure structural container:
InputReader1 -> AAM1 -> ANV1 -> PV1 -> BPM1 -> TPM1

All stdout JSONL emission and stdin reading are handled by the atomic sub-models.
"""

from xdevs.models import Atomic, Coupled, Port

from .IOBS_D1_libs.InputReader1 import InputReader1
from .IOBS_D1_libs.AAM1 import AAM1
from .IOBS_D1_libs.ANV1 import ANV1
from .IOBS_D1_libs.PV1 import PV1
from .IOBS_D1_libs.BPM1 import BPM1
from .IOBS_D1_libs.TPM1 import TPM1


class IOBS_D1(Coupled):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        processing_delay_s: float,
        tpm_initial_balance: int,
        bpm_bill_amount_min: int,
        bpm_bill_amount_max: int,
    ):
        super().__init__(name)
        self.parent = parent

        # No boundary ports (locked contract)

        input_reader1 = InputReader1(name="input_reader1", parent=self)
        aam1 = AAM1(name="AAM1", parent=self, processing_delay_s=processing_delay_s)
        anv1 = ANV1(name="ANV1", parent=self, processing_delay_s=processing_delay_s)
        pv1 = PV1(name="PV1", parent=self, processing_delay_s=processing_delay_s)
        bpm1 = BPM1(
            name="BPM1",
            parent=self,
            processing_delay_s=processing_delay_s,
            bill_amount_min=bpm_bill_amount_min,
            bill_amount_max=bpm_bill_amount_max,
            initial_balance=tpm_initial_balance,
        )
        tpm1 = TPM1(
            name="TPM1",
            parent=self,
            processing_delay_s=processing_delay_s,
            initial_balance=tpm_initial_balance,
        )

        self.add_component(input_reader1)
        self.add_component(aam1)
        self.add_component(anv1)
        self.add_component(pv1)
        self.add_component(bpm1)
        self.add_component(tpm1)

        # Internal couplings (pipeline)
        self.add_coupling(input_reader1.output["request_out"], aam1.input["request_in"])
        self.add_coupling(aam1.output["to_anv"], anv1.input["request_in"])
        self.add_coupling(anv1.output["to_pv"], pv1.input["request_in"])
        self.add_coupling(pv1.output["to_bpm"], bpm1.input["request_in"])
        self.add_coupling(bpm1.output["bill_out"], tpm1.input["bill_in"])