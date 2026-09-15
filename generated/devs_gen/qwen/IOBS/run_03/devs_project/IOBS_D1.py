"""IOBS_D1: Coupled DEVS model orchestrating the IOBS_D1 simulation pipeline."""

from xdevs.models import Atomic, Coupled, Port

from .IOBS_D1_libs.InputReader1 import InputReader1
from .IOBS_D1_libs.AAM1 import AAM1
from .IOBS_D1_libs.ANV1 import ANV1
from .IOBS_D1_libs.PV1 import PV1
from .IOBS_D1_libs.BPM1 import BPM1
from .IOBS_D1_libs.TPM1 import TPM1


class IOBS_D1(Coupled):
    """Orchestrates the IOBS_D1 simulation pipeline from input parsing to final transaction reporting."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulation_time: float = 1000000.0,
    ):
        super().__init__(name)
        self.parent = parent

        # Instantiate all child components
        input_reader1 = InputReader1(
            name="input_reader1",
            parent=self,
        )
        aam1 = AAM1(
            name="AAM1",
            parent=self,
            processing_delay=10.0,
        )
        anv1 = ANV1(
            name="ANV1",
            parent=self,
            processing_delay=10.0,
        )
        pv1 = PV1(
            name="PV1",
            parent=self,
            processing_delay=10.0,
        )
        bpm1 = BPM1(
            name="BPM1",
            parent=self,
            processing_delay=10.0,
        )
        tpm1 = TPM1(
            name="TPM1",
            parent=self,
            processing_delay=10.0,
            initial_balance=3000,
        )

        # Register components
        self.add_component(input_reader1)
        self.add_component(aam1)
        self.add_component(anv1)
        self.add_component(pv1)
        self.add_component(bpm1)
        self.add_component(tpm1)

        # Define couplings as per the locked contract
        self.add_coupling(
            input_reader1.output["request_out"],
            aam1.input["request_in"],
        )
        self.add_coupling(
            aam1.output["account_out"],
            anv1.input["account_in"],
        )
        self.add_coupling(
            anv1.output["account_out"],
            pv1.input["account_in"],
        )
        self.add_coupling(
            pv1.output["account_out"],
            bpm1.input["account_in"],
        )
        self.add_coupling(
            bpm1.output["amount_out"],
            tpm1.input["amount_in"],
        )