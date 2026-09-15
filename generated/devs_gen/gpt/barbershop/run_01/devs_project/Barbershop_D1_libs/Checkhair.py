"""Atomic DEVS model: Checkhair (Hair Inspection coordinator)."""

import json
import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class Checkhair(Atomic):
    # Phase labels (enum-like)
    IDLE_AVAILABLE = "IDLE_AVAILABLE"
    CONSULTING = "CONSULTING"
    WAITING_CUT_DONE = "WAITING_CUT_DONE"
    ANNOUNCE_AVAILABLE = "ANNOUNCE_AVAILABLE"
    FORWARD_TO_CUT = "FORWARD_TO_CUT"

    def __init__(self, name: str, parent: Coupled | None, consult_time_s: float):
        super().__init__(name)
        self.parent = parent
        self.consult_time_s = float(consult_time_s)

        # Ports (locked contract)
        self.add_in_port(Port(str, "cust_in"))
        self.add_in_port(Port(str, "cut_done_in"))

        self.add_out_port(Port(str, "to_cut"))
        self.add_out_port(Port(str, "to_reception"))
        self.add_out_port(Port(bool, "available_out"))

        # Remembered state (locked contract)
        self.available: bool = True
        self.customer: str | None = None
        self.pending_forward: bool = False

        # Prepared outputs for lambdaf
        self._announce_available_value: bool | None = None
        self._to_cut_payload: str | None = None
        self._to_reception_payload: str | None = None

    def initialize(self):
        if self.consult_time_s < 0.0:
            raise ValueError("consult_time_s must be nonnegative")

        self.available = True
        self.customer = None
        self.pending_forward = False

        self._announce_available_value = True
        self._to_cut_payload = None
        self._to_reception_payload = None

        # Must actively emit available_out=True at t=0.0 (no JSONL required).
        self.hold_in(self.ANNOUNCE_AVAILABLE, 0.0)

    def _warn(self, msg: str) -> None:
        print(f"[checkhair warning] {msg}", file=sys.stderr, flush=True)

    def _log_state_customer(self, now: float, value: str) -> None:
        print(
            json.dumps(
                {
                    "time": float(now),
                    "type": "state",
                    "model": "checkhair",
                    "field": "customer",
                    "value": value,
                }
            ),
            flush=True,
        )

    def _log_message(self, now: float, port: str, content: str) -> None:
        print(
            json.dumps(
                {
                    "time": float(now),
                    "type": "message",
                    "model": "checkhair",
                    "port": port,
                    "content": content,
                }
            ),
            flush=True,
        )

    def deltext(self, e: float):
        # Keep remaining time if already active.
        if self.phase in (self.CONSULTING, self.ANNOUNCE_AVAILABLE, self.FORWARD_TO_CUT):
            self.continuef(e)

        now = get_current_time()

        # Handle new customer arrivals
        for msg in self.input["cust_in"].values:
            if msg != "newcust":
                self._warn(f"Unexpected cust_in content {msg!r}; ignoring.")
                continue

            if self.available and self.phase == self.IDLE_AVAILABLE:
                # Accept
                self.available = False
                self._announce_available_value = False  # emit at time t
                self.customer = "newcust"
                self._log_state_customer(now, "newcust")

                # Emit availability change immediately via DEVS output at same t
                # (schedule zero-delay internal event for lambdaf).
                if self.consult_time_s == 0.0:
                    # Ensure ordering: state('newcust') already logged above, then to_cut at same t.
                    self.pending_forward = True
                    self.hold_in(self.FORWARD_TO_CUT, 0.0)
                else:
                    self.hold_in(self.CONSULTING, self.consult_time_s)
                return
            else:
                self._warn("Received 'newcust' while busy; ignoring.")
                continue

        # Handle cut done signals
        for msg in self.input["cut_done_in"].values:
            if msg != "done":
                self._warn(f"Unexpected cut_done_in content {msg!r}; ignoring.")
                continue

            if self.phase == self.WAITING_CUT_DONE:
                # On receipt at time t: log state, then send done to reception, then become available and emit availability True.
                self.customer = "done"
                self._log_state_customer(now, "done")

                self._to_reception_payload = "done"
                self._announce_available_value = True
                self.available = True

                self.hold_in(self.ANNOUNCE_AVAILABLE, 0.0)
                return
            else:
                self._warn("Received 'done' while not waiting for cut completion; ignoring.")
                continue

        # If nothing meaningful happened and we were passive, remain/passivate appropriately.
        if self.phase not in (self.CONSULTING, self.ANNOUNCE_AVAILABLE, self.FORWARD_TO_CUT):
            # Keep current phase (likely IDLE_AVAILABLE or WAITING_CUT_DONE)
            if self.phase == self.IDLE_AVAILABLE:
                self.passivate(self.IDLE_AVAILABLE)
            elif self.phase == self.WAITING_CUT_DONE:
                self.passivate(self.WAITING_CUT_DONE)

    def lambdaf(self):
        now = get_current_time()

        # Availability announcements can coincide with other outputs; ensure causal ordering requirements.
        if self.phase == self.ANNOUNCE_AVAILABLE:
            # If we have a pending to_reception message, it must be logged after state('done')
            # which was already logged in deltext at the same time.
            if self._to_reception_payload is not None:
                self.output["to_reception"].add(self._to_reception_payload)
                self._log_message(now, "to_reception", self._to_reception_payload)
            if self._announce_available_value is not None:
                self.output["available_out"].add(bool(self._announce_available_value))

        elif self.phase == self.FORWARD_TO_CUT:
            # Consult completion: send to_cut and log message.
            if self.pending_forward:
                self.output["to_cut"].add("newcust")
                self._log_message(now, "to_cut", "newcust")

            # Also emit availability change if it was prepared (e.g., acceptance at same time)
            if self._announce_available_value is not None:
                self.output["available_out"].add(bool(self._announce_available_value))

        elif self.phase == self.CONSULTING:
            # No outputs at the end of CONSULTING directly; we use deltint to move to FORWARD_TO_CUT.
            pass

    def deltint(self):
        if self.phase == self.ANNOUNCE_AVAILABLE:
            # Clear outputs prepared for this event
            self._to_reception_payload = None
            self._announce_available_value = None

            # After notifying reception, become idle available; otherwise keep waiting.
            if self.available:
                self.passivate(self.IDLE_AVAILABLE)
            else:
                # Busy but just announced False; continue consulting if scheduled elsewhere (shouldn't happen here)
                self.passivate(self.CONSULTING)

        elif self.phase == self.CONSULTING:
            # Consultation finished: schedule immediate forward to cut.
            self.pending_forward = True
            self.hold_in(self.FORWARD_TO_CUT, 0.0)

        elif self.phase == self.FORWARD_TO_CUT:
            # After forwarding, wait for cut done.
            self.pending_forward = False
            self._to_cut_payload = None
            self._announce_available_value = None
            self.passivate(self.WAITING_CUT_DONE)

        else:
            # Any other internal event shouldn't occur; remain passive.
            self.passivate(self.phase)

    def exit(self):
        pass