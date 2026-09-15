"""IOBS_D1: Top-level coupled model for the IOBS_D1 system."""

from xdevs.models import Atomic, Coupled, Port

from .IOBS_D1_libs.InputReader1 import InputReader1
from .IOBS_D1_libs.AAM1 import AAM1
from .IOBS_D1_libs.ANV1 import ANV1
from .IOBS_D1_libs.PV1 import PV1
from .IOBS_D1_libs.BPM1 import BPM1
from .IOBS_D1_libs.TPM1 import TPM1


class IOBS_D1(Coupled):
    """Orchestrates the flow of authentication and transaction requests through the processing pipeline."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulation_time: float = 1000000.0,
    ):
        super().__init__(name)
        self.parent = parent

        # Instantiate child components
        input_reader1 = InputReader1(name="InputReader1", parent=self)
        aam1 = AAM1(name="AAM1", parent=self)
        anv1 = ANV1(name="ANV1", parent=self)
        pv1 = PV1(name="PV1", parent=self)
        bpm1 = BPM1(name="BPM1", parent=self)
        tpm1 = TPM1(name="TPM1", parent=self, initial_balance=3000)

        # Register components
        self.add_component(input_reader1)
        self.add_component(aam1)
        self.add_component(anv1)
        self.add_component(pv1)
        self.add_component(bpm1)
        self.add_component(tpm1)

        # Define couplings as per the locked contract
        self.add_coupling(
            input_reader1.output["input"],
            aam1.input["input"],
        )
        self.add_coupling(
            aam1.output["account_generated"],
            anv1.input["account_generated"],
        )
        self.add_coupling(
            anv1.output["verification"],
            pv1.input["verification"],
        )
        self.add_coupling(
            pv1.output["verification"],
            bpm1.input["verification"],
        )
        self.add_coupling(
            bpm1.output["bill"],
            tpm1.input["bill"],
        )