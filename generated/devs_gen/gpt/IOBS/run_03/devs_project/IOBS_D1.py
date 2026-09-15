"""IOBS_D1: Top-level coupled DEVS model composing the IOBS pipeline.

Structure:
InputReader1 → AAM1 → ANV1 → PV1 → BPM1 → TPM1
and feedback TPM1.balance_update_out → BPM1.balance_update_in

This coupled model is portless and performs only structural composition and
couplings. All stdin parsing, random decisions, timing delays, and JSONL output
are handled by the atomic sub-models.
"""

from xdevs.models import Atomic, Coupled, Port

from .IOBS_D1_libs.InputReader1 import InputReader1
from .IOBS_D1_libs.AAM1 import AAM1
from .IOBS_D1_libs.ANV1 import ANV1
from .IOBS_D1_libs.PV1 import PV1
from .IOBS_D1_libs.BPM1 import BPM1
from .IOBS_D1_libs.TPM1 import TPM1


class IOBS_D1(Coupled):
    """Top-level coupled DEVS model for the Internet Online Banking System."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        stage_delay_s: float,
        tpm_initial_balance: int,
        bpm_bill_min: int,
        bpm_bill_max: int,
        anv_pass_probability: float,
        pv_success_probability: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Children
        input_reader1 = InputReader1(name="input_reader1", parent=self)
        aam1 = AAM1(name="AAM1", parent=self, stage_delay_s=stage_delay_s)
        anv1 = ANV1(
            name="ANV1",
            parent=self,
            stage_delay_s=stage_delay_s,
            pass_probability=anv_pass_probability,
        )
        pv1 = PV1(
            name="PV1",
            parent=self,
            stage_delay_s=stage_delay_s,
            success_probability=pv_success_probability,
        )
        bpm1 = BPM1(
            name="BPM1",
            parent=self,
            stage_delay_s=stage_delay_s,
            bill_min=bpm_bill_min,
            bill_max=bpm_bill_max,
            initial_remaining_balance=tpm_initial_balance,
        )
        tpm1 = TPM1(
            name="TPM1",
            parent=self,
            stage_delay_s=stage_delay_s,
            initial_balance=tpm_initial_balance,
        )

        # Register components
        self.add_component(input_reader1)
        self.add_component(aam1)
        self.add_component(anv1)
        self.add_component(pv1)
        self.add_component(bpm1)
        self.add_component(tpm1)

        # Couplings (pipeline)
        self.add_coupling(input_reader1.output["request_out"], aam1.input["request_in"])
        self.add_coupling(aam1.output["to_anv"], anv1.input["request_in"])
        self.add_coupling(anv1.output["to_pv"], pv1.input["request_in"])
        self.add_coupling(pv1.output["to_bpm"], bpm1.input["request_in"])
        self.add_coupling(bpm1.output["bill_out"], tpm1.input["bill_in"])

        # Feedback coupling (balance updates)
        self.add_coupling(
            tpm1.output["balance_update_out"],
            bpm1.input["balance_update_in"],
        )