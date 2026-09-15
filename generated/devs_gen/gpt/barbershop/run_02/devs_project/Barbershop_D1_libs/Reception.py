import json
import sys
from collections import deque

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Reception(Atomic):
    """
    Atomic DEVS model: barbershop reception desk.

    - Bounded FIFO queue (tokens, no IDs), capacity = queue_capacity.
    - Deterministic check-in service for head-of-line customer, duration = checkin_time_s.
    - Handoff to CheckHair only when checkhair_available is True.
    - Logs ONLY required JSONL business records to stdout.
    """

    def __init__(self, name: str, parent: Coupled | None, queue_capacity: int, checkin_time_s: float):
        super().__init__(name)
        self.parent = parent
        self.queue_capacity = int(queue_capacity)
        self.checkin_time_s = float(checkin_time_s)

        self.add_in_port(Port(dict, "arrival_in"))
        self.add_in_port(Port(dict, "checkhair_available_in"))
        self.add_in_port(Port(dict, "service_done_in"))

        self.add_out_port(Port(dict, "cust"))

        # State
        self.queue: deque[object] = deque()
        self.checkhair_available: bool = False

        # Head-of-line processing flags
        self.checkin_running: bool = False
        self.ready_to_send: bool = False

        # Output preparation
        self._cust_payload_to_send: dict | None = None
        self._do_handoff_after_output: bool = False  # pop+log+maybe start next in deltint

    def _log_state_queue_len(self) -> None:
        # Type A state record
        print(
            json.dumps(
                {
                    "time": float(get_current_time()),
                    "type": "state",
                    "model": "reception",
                    "field": "total customers num",
                    "value": int(len(self.queue)),
                }
            ),
            flush=True,
        )

    def _log_message_cust(self) -> None:
        # Type B message record
        print(
            json.dumps(
                {
                    "time": float(get_current_time()),
                    "type": "message",
                    "model": "reception",
                    "port": "cust",
                    "content": "newcust",
                }
            ),
            flush=True,
        )

    def _start_checkin_if_needed(self) -> None:
        # Start check-in only if queue non-empty and not already running and not blocked ready_to_send
        if len(self.queue) == 0:
            return
        if self.checkin_running or self.ready_to_send:
            return

        self.checkin_running = True
        if self.checkin_time_s <= 0.0:
            # Immediate completion: schedule internal event now
            self.hold_in("CHECKIN_COMPLETE", 0.0)
        else:
            self.hold_in("CHECKIN_RUNNING", self.checkin_time_s)

    def _prepare_handoff_output(self) -> None:
        # Prepare a cust output (must be followed by pop in deltint)
        self._cust_payload_to_send = {"event": "newcust"}
        self._do_handoff_after_output = True
        self.hold_in("SEND_CUST", 0.0)

    def initialize(self):
        self.queue = deque()
        self.checkhair_available = False
        self.checkin_running = False
        self.ready_to_send = False
        self._cust_payload_to_send = None
        self._do_handoff_after_output = False
        self.passivate("IDLE")

    def deltext(self, e: float):
        # Preserve remaining time if currently active (including sigma=0 phases)
        if self.phase != "passive" and self.sigma != float("inf"):
            self.continuef(e)

        # Process availability updates first (order within bag not guaranteed; this is safe)
        for msg in self.input["checkhair_available_in"].values:
            if isinstance(msg, dict) and "available" in msg:
                self.checkhair_available = bool(msg["available"])
                if self.ready_to_send and self.checkhair_available:
                    # Immediate handoff at same timestamp
                    self._prepare_handoff_output()

        # service_done_in: accept but no queue effect
        for msg in self.input["service_done_in"].values:
            # Optional diagnostics only; must not write JSONL to stdout
            # Keep silent by default.
            _ = msg

        # Handle arrivals
        for msg in self.input["arrival_in"].values:
            if not (isinstance(msg, dict) and msg.get("event") == "newcust"):
                continue

            if len(self.queue) < self.queue_capacity:
                self.queue.append(object())
                self._log_state_queue_len()

                # If idle, start check-in immediately (no state log)
                if not self.checkin_running and not self.ready_to_send:
                    self._start_checkin_if_needed()
            else:
                # Ignore arrival: no state change, no stdout record
                pass

        # If we were passive and got no scheduling from above, remain/passivate
        if self.phase == "passive":
            self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "SEND_CUST" and self._cust_payload_to_send is not None:
            self.output["cust"].add(dict(self._cust_payload_to_send))
            self._log_message_cust()

    def deltint(self):
        if self.phase == "CHECKIN_RUNNING" or self.phase == "CHECKIN_COMPLETE":
            # Check-in timer completed now
            self.checkin_running = False
            self.ready_to_send = True

            if self.checkhair_available:
                self._prepare_handoff_output()
            else:
                # Block until availability becomes True
                self.passivate("WAIT_AVAILABLE")

        elif self.phase == "SEND_CUST":
            # After output, perform the actual handoff effects: pop + state log + start next
            if self._do_handoff_after_output:
                # Must never emit cust unless removing exactly one customer
                if len(self.queue) > 0 and self.ready_to_send:
                    self.queue.popleft()
                    self._log_state_queue_len()
                else:
                    # Inconsistent state; diagnostics only
                    print(
                        f"[reception] Warning: SEND_CUST without ready customer or empty queue at t={get_current_time()}",
                        file=sys.stderr,
                        flush=True,
                    )

                self.ready_to_send = False
                self._do_handoff_after_output = False

                # Start next check-in immediately if queue non-empty
                if len(self.queue) > 0:
                    self._cust_payload_to_send = None
                    self._start_checkin_if_needed()
                else:
                    self._cust_payload_to_send = None
                    self.passivate("IDLE")
            else:
                self._cust_payload_to_send = None
                self.passivate("IDLE")

        elif self.phase == "WAIT_AVAILABLE":
            # Should only be reactivated by external availability message
            self.passivate("WAIT_AVAILABLE")

        else:
            self.passivate("IDLE")

    def exit(self):
        pass