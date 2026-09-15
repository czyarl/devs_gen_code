import json
import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class CheckHair(Atomic):
    PHASE_AVAILABLE = "AVAILABLE"
    PHASE_CONSULTING = "CONSULTING"
    PHASE_WAITING_CUT_DONE = "WAITING_CUT_DONE"

    PHASE_OUTPUT_AVAIL_TRUE = "OUTPUT_AVAIL_TRUE"
    PHASE_OUTPUT_AVAIL_FALSE = "OUTPUT_AVAIL_FALSE"
    PHASE_OUTPUT_TO_CUT = "OUTPUT_TO_CUT"
    PHASE_OUTPUT_DONE_SEQUENCE = "OUTPUT_DONE_SEQUENCE"

    def __init__(self, name: str, parent: Coupled | None, consult_time_s: float):
        super().__init__(name)
        self.parent = parent
        self.consult_time_s = float(consult_time_s)

        # Ports (locked contract)
        self.add_in_port(Port(dict, "cust_in"))
        self.add_in_port(Port(dict, "cut_done_in"))

        self.add_out_port(Port(dict, "to_cut"))
        self.add_out_port(Port(dict, "to_reception"))
        self.add_out_port(Port(dict, "availability_out"))

        # State
        self.phase = self.PHASE_AVAILABLE
        self.customer_field: str | None = None

        # Pending outputs / sequence control
        self._pending_availability: bool | None = None
        self._pending_to_cut: bool = False
        self._done_seq_step: int = 0  # 0=none, 1=state logged, 2=to_reception emitted, 3=availability emitted
        self._pending_done_time: float | None = None

    def initialize(self):
        if self.consult_time_s < 0.0:
            raise ValueError("consult_time_s must be nonnegative")

        self.phase = self.PHASE_AVAILABLE
        self.customer_field = None

        self._pending_availability = True  # startup True
        self._pending_to_cut = False
        self._done_seq_step = 0
        self._pending_done_time = None

        # Must actively emit availability_out {'available': True} at t=0.0
        self.hold_in(self.PHASE_OUTPUT_AVAIL_TRUE, 0.0)

    # --------- helpers (external IO) ---------
    def _stdout_state_customer(self, t: float, value: str) -> None:
        record = {
            "time": float(t),
            "type": "state",
            "model": "checkhair",
            "field": "customer",
            "value": value,
        }
        print(json.dumps(record), flush=True)

    def _stdout_message(self, t: float, port: str, content: str) -> None:
        record = {
            "time": float(t),
            "type": "message",
            "model": "checkhair",
            "port": port,
            "content": content,
        }
        print(json.dumps(record), flush=True)

    def _warn(self, msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    # --------- DEVS transitions ---------
    def deltext(self, e: float):
        # Handle external events according to current phase; ignore malformed/duplicate.
        # Preserve remaining time when staying in same active phase.
        handled = False

        if self.phase == self.PHASE_AVAILABLE:
            for packet in self.input["cust_in"].values:
                if not isinstance(packet, dict) or packet.get("event") != "newcust":
                    self._warn(f"[checkhair] Ignored malformed cust_in payload: {packet!r}")
                    continue

                # Accept only when AVAILABLE
                t = get_current_time()
                self.phase = self.PHASE_CONSULTING

                # Update tracked variable and emit Type A immediately
                self.customer_field = "newcust"
                self._stdout_state_customer(t, "newcust")

                # Optionally emit availability_out False immediately: we do emit it.
                self._pending_availability = False
                self.hold_in(self.PHASE_OUTPUT_AVAIL_FALSE, 0.0)
                handled = True
                break

            if handled:
                return

        elif self.phase == self.PHASE_CONSULTING:
            # Ignore cust_in while not AVAILABLE
            for packet in self.input["cust_in"].values:
                if isinstance(packet, dict) and packet.get("event") == "newcust":
                    self._warn("[checkhair] Ignored cust_in while busy (CONSULTING).")
                else:
                    self._warn(f"[checkhair] Ignored malformed cust_in payload: {packet!r}")

            # Ignore cut_done_in while CONSULTING
            for packet in self.input["cut_done_in"].values:
                if isinstance(packet, dict) and packet.get("event") == "done":
                    self._warn("[checkhair] Ignored cut_done_in while CONSULTING.")
                else:
                    self._warn(f"[checkhair] Ignored malformed cut_done_in payload: {packet!r}")

            self.continuef(e)
            return

        elif self.phase == self.PHASE_WAITING_CUT_DONE:
            for packet in self.input["cut_done_in"].values:
                if not isinstance(packet, dict) or packet.get("event") != "done":
                    self._warn(f"[checkhair] Ignored malformed cut_done_in payload: {packet!r}")
                    continue

                # Accept only when WAITING_CUT_DONE
                t = get_current_time()

                # Ordering requirement: write Type A state('done') first
                self.customer_field = "done"
                self._stdout_state_customer(t, "done")

                # Then send/log to_reception, then emit availability True.
                self._pending_done_time = t
                self._done_seq_step = 1
                self.hold_in(self.PHASE_OUTPUT_DONE_SEQUENCE, 0.0)
                handled = True
                break

            if handled:
                return

            # Ignore cust_in while waiting for cut done
            for packet in self.input["cust_in"].values:
                if isinstance(packet, dict) and packet.get("event") == "newcust":
                    self._warn("[checkhair] Ignored cust_in while busy (WAITING_CUT_DONE).")
                else:
                    self._warn(f"[checkhair] Ignored malformed cust_in payload: {packet!r}")

            self.continuef(e)
            return

        else:
            # Output phases: ignore all inputs, keep scheduled internal event
            self.continuef(e)
            return

        # Default: if nothing handled and no continuef already called
        self.continuef(e)

    def lambdaf(self):
        t = get_current_time()

        if self.phase == self.PHASE_OUTPUT_AVAIL_TRUE:
            # Startup or post-completion availability True
            if self._pending_availability is True:
                self.output["availability_out"].add({"available": True})

        elif self.phase == self.PHASE_OUTPUT_AVAIL_FALSE:
            if self._pending_availability is False:
                self.output["availability_out"].add({"available": False})

        elif self.phase == self.PHASE_OUTPUT_TO_CUT:
            if self._pending_to_cut:
                self.output["to_cut"].add({"event": "newcust"})
                # Type B message record at same time
                self._stdout_message(t, "to_cut", "newcust")

        elif self.phase == self.PHASE_OUTPUT_DONE_SEQUENCE:
            # Must preserve ordering at same time:
            # state('done') already printed in deltext, now:
            # send/log to_reception, then emit availability True (after notification sent)
            if self._done_seq_step == 1:
                self.output["to_reception"].add({"event": "done"})
                self._stdout_message(t, "to_reception", "done")
                self._done_seq_step = 2
            elif self._done_seq_step == 2:
                self.output["availability_out"].add({"available": True})
                self._done_seq_step = 3

    def deltint(self):
        # Advance state after internal events
        if self.phase == self.PHASE_OUTPUT_AVAIL_TRUE:
            self._pending_availability = None
            self.phase = self.PHASE_AVAILABLE
            self.passivate(self.PHASE_AVAILABLE)

        elif self.phase == self.PHASE_OUTPUT_AVAIL_FALSE:
            self._pending_availability = None
            # Now schedule consultation completion after consult_time_s
            self.phase = self.PHASE_CONSULTING
            self.hold_in(self.PHASE_CONSULTING, self.consult_time_s)

        elif self.phase == self.PHASE_CONSULTING:
            # Consultation timer fired: next internal event must emit to_cut at same time
            self._pending_to_cut = True
            self.hold_in(self.PHASE_OUTPUT_TO_CUT, 0.0)

        elif self.phase == self.PHASE_OUTPUT_TO_CUT:
            # lambdaf emitted to_cut and logged it
            self._pending_to_cut = False
            self.phase = self.PHASE_WAITING_CUT_DONE
            self.passivate(self.PHASE_WAITING_CUT_DONE)

        elif self.phase == self.PHASE_OUTPUT_DONE_SEQUENCE:
            if self._done_seq_step == 2:
                # After emitting to_reception, must emit availability True at same time
                self.hold_in(self.PHASE_OUTPUT_DONE_SEQUENCE, 0.0)
            elif self._done_seq_step == 3:
                # After availability True, become AVAILABLE
                self._done_seq_step = 0
                self._pending_done_time = None
                self.phase = self.PHASE_AVAILABLE
                self.passivate(self.PHASE_AVAILABLE)
            else:
                # Should not happen; fail safe
                self._done_seq_step = 0
                self._pending_done_time = None
                self.phase = self.PHASE_AVAILABLE
                self.passivate(self.PHASE_AVAILABLE)

        else:
            self.phase = self.PHASE_AVAILABLE
            self.passivate(self.PHASE_AVAILABLE)

    def exit(self):
        # No special finalization output required.
        pass