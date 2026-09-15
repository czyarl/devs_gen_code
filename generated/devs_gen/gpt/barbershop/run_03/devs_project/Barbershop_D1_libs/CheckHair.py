import json
import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class CheckHair(Atomic):
    """
    Atomic DEVS model: Hair Inspection phase.

    Locked interface:
      Inputs:
        - cust_in: str ('newcust')
        - cut_done_in: str ('done')
      Outputs:
        - to_cut: str ('newcust')
        - to_reception: str ('done')
        - available_out: bool (True)
    """

    PHASE_AVAILABLE = "AVAILABLE"
    PHASE_CONSULTING = "CONSULTING"
    PHASE_WAIT_DONE = "WAIT_CUT_DONE"
    PHASE_OUTPUT_STARTUP_AVAIL = "OUTPUT_STARTUP_AVAIL"
    PHASE_OUTPUT_TO_CUT = "OUTPUT_TO_CUT"
    PHASE_OUTPUT_DONE_AND_AVAIL = "OUTPUT_DONE_AND_AVAIL"

    def __init__(self, name: str, parent: Coupled | None, consult_time_s: float):
        super().__init__(name)
        self.parent = parent
        self.consult_time_s = float(consult_time_s)

        self.add_in_port(Port(str, "cust_in"))
        self.add_in_port(Port(str, "cut_done_in"))

        self.add_out_port(Port(str, "to_cut"))
        self.add_out_port(Port(str, "to_reception"))
        self.add_out_port(Port(bool, "available_out"))

        # Remembered state
        self._available: bool = True
        self._phase_flag: str = self.PHASE_AVAILABLE  # consulting / waiting / available
        self._consult_deadline: float | None = None

        # Output preparation flags
        self._emit_startup_available: bool = False
        self._emit_to_cut: bool = False
        self._emit_done_and_available: bool = False

    def initialize(self):
        self._available = True
        self._phase_flag = self.PHASE_AVAILABLE
        self._consult_deadline = None

        self._emit_startup_available = True
        self._emit_to_cut = False
        self._emit_done_and_available = False

        # Must emit available_out=True at t=0.0 (no JSONL required for availability).
        self.hold_in(self.PHASE_OUTPUT_STARTUP_AVAIL, 0.0)

    def deltext(self, e: float):
        # External events never directly emit outputs; schedule 0-delay output phases.
        if self.phase == self.PHASE_AVAILABLE:
            accepted = False
            for token in self.input["cust_in"].values:
                if token != "newcust":
                    continue
                if not self._available:
                    continue
                # Accept customer
                t = float(get_current_time())
                self._available = False
                self._phase_flag = self.PHASE_CONSULTING
                self._consult_deadline = t + self.consult_time_s

                # Type A state-change record: customer becomes 'newcust'
                print(
                    json.dumps(
                        {
                            "time": t,
                            "type": "state",
                            "model": "checkhair",
                            "field": "customer",
                            "value": "newcust",
                        }
                    ),
                    flush=True,
                )

                # Schedule forwarding after deterministic consultation time
                self._emit_to_cut = True
                self.hold_in(self.PHASE_OUTPUT_TO_CUT, max(0.0, self.consult_time_s))
                accepted = True
                break

            if not accepted:
                # Ignore other inputs; remain passivated
                self.continuef(e)

        elif self.phase == self.PHASE_OUTPUT_TO_CUT:
            # Preserve remaining time to the internal event; ignore inputs while busy.
            self.continuef(e)

        elif self.phase == self.PHASE_WAIT_DONE:
            handled = False
            for token in self.input["cut_done_in"].values:
                if token != "done":
                    continue
                if self._phase_flag != self.PHASE_WAIT_DONE:
                    continue

                t_done = float(get_current_time())

                # Type A state-change record: customer becomes 'done'
                print(
                    json.dumps(
                        {
                            "time": t_done,
                            "type": "state",
                            "model": "checkhair",
                            "field": "customer",
                            "value": "done",
                        }
                    ),
                    flush=True,
                )

                # Prepare immediate outputs: to_reception='done' and available_out=True
                self._emit_done_and_available = True
                self.hold_in(self.PHASE_OUTPUT_DONE_AND_AVAIL, 0.0)
                handled = True
                break

            if not handled:
                self.continuef(e)

        elif self.phase in (self.PHASE_OUTPUT_STARTUP_AVAIL, self.PHASE_OUTPUT_DONE_AND_AVAIL):
            # If external input arrives while a 0-delay output is pending, keep output pending.
            self.continuef(e)
        else:
            self.continuef(e)

    def lambdaf(self):
        t = float(get_current_time())

        if self.phase == self.PHASE_OUTPUT_STARTUP_AVAIL and self._emit_startup_available:
            self.output["available_out"].add(True)

        elif self.phase == self.PHASE_OUTPUT_TO_CUT and self._emit_to_cut:
            # Send to CutHair and log Type B message record at the same time.
            self.output["to_cut"].add("newcust")
            print(
                json.dumps(
                    {
                        "time": t,
                        "type": "message",
                        "model": "checkhair",
                        "port": "to_cut",
                        "content": "newcust",
                    }
                ),
                flush=True,
            )

        elif self.phase == self.PHASE_OUTPUT_DONE_AND_AVAIL and self._emit_done_and_available:
            # Send 'done' to reception and log Type B message record at the same time.
            self.output["to_reception"].add("done")
            print(
                json.dumps(
                    {
                        "time": t,
                        "type": "message",
                        "model": "checkhair",
                        "port": "to_reception",
                        "content": "done",
                    }
                ),
                flush=True,
            )
            # Also emit availability True at the same simulation time (no JSONL required).
            self.output["available_out"].add(True)

    def deltint(self):
        if self.phase == self.PHASE_OUTPUT_STARTUP_AVAIL:
            self._emit_startup_available = False
            self.passivate(self.PHASE_AVAILABLE)

        elif self.phase == self.PHASE_OUTPUT_TO_CUT:
            # After forwarding to CutHair, wait for completion; remain unavailable.
            self._emit_to_cut = False
            self._phase_flag = self.PHASE_WAIT_DONE
            self.passivate(self.PHASE_WAIT_DONE)

        elif self.phase == self.PHASE_OUTPUT_DONE_AND_AVAIL:
            # After notifying reception, become available again.
            self._emit_done_and_available = False
            self._available = True
            self._phase_flag = self.PHASE_AVAILABLE
            self._consult_deadline = None
            self.passivate(self.PHASE_AVAILABLE)

        else:
            # Safety fallback
            self.passivate(self.PHASE_AVAILABLE)

    def exit(self):
        pass