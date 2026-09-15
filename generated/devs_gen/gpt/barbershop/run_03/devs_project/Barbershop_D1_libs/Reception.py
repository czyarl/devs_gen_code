import json
import sys

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Reception(Atomic):
    """
    Atomic DEVS model representing the barbershop reception waiting area and check-in server.

    Locked interface:
      Inputs:
        - arrival_in: str ('newcust')
        - barber_done_in: str ('done')
        - checkhair_available_in: bool
      Outputs:
        - cust: str ('newcust')
    """

    PHASE_IDLE = "IDLE"
    PHASE_CHECKIN = "CHECKIN"
    PHASE_BLOCKED = "BLOCKED"          # check-in completed, waiting for availability
    PHASE_SEND_READY = "SEND_READY"    # internal 0-delay phase to emit 'cust'

    def __init__(self, name: str, parent: Coupled | None, capacity: int, checkin_time_s: float):
        super().__init__(name)
        self.parent = parent
        self.capacity = capacity
        self.checkin_time_s = checkin_time_s

        self.add_in_port(Port(str, "arrival_in"))
        self.add_in_port(Port(str, "barber_done_in"))
        self.add_in_port(Port(bool, "checkhair_available_in"))
        self.add_out_port(Port(str, "cust"))

        # State
        self.queue_count: int = 0
        self.tracked_total_customers_num: int = 0
        self.checkhair_available: bool = False

        # Control / output prep
        self._pending_send: bool = False

    # ---------- stdout/stderr helpers ----------
    def _stdout_state_total_customers(self) -> None:
        record = {
            "time": float(get_current_time()),
            "type": "state",
            "model": "reception",
            "field": "total customers num",
            "value": int(self.tracked_total_customers_num),
        }
        print(json.dumps(record), flush=True)

    def _stdout_message_send_newcust(self) -> None:
        record = {
            "time": float(get_current_time()),
            "type": "message",
            "model": "reception",
            "port": "cust",
            "content": "newcust",
        }
        print(json.dumps(record), flush=True)

    def _warn(self, msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    # ---------- internal mechanics ----------
    def _start_checkin_if_possible(self) -> None:
        # Start check-in only when we have someone to process and we're not already in progress
        if self.queue_count > 0 and self.phase == self.PHASE_IDLE:
            self.hold_in(self.PHASE_CHECKIN, float(self.checkin_time_s))

    def _schedule_send_now(self) -> None:
        # Prepare a zero-delay internal event to send one customer to CheckHair
        self._pending_send = True
        self.hold_in(self.PHASE_SEND_READY, 0.0)

    # ---------- DEVS lifecycle ----------
    def initialize(self):
        self.queue_count = 0
        self.tracked_total_customers_num = 0
        self.checkhair_available = False
        self._pending_send = False
        self.passivate(self.PHASE_IDLE)

    def deltext(self, e: float):
        # Same-time ordering rule is satisfied by default xDEVS (deltint before deltext at same t).
        # Preserve remaining time if currently active (CHECKIN/BLOCKED/SEND_READY).
        if self.phase != self.PHASE_IDLE:
            self.continuef(e)

        # Process availability updates first (can unblock immediate send at same time)
        for avail in self.input["checkhair_available_in"].values:
            if isinstance(avail, bool):
                self.checkhair_available = bool(avail)
                if avail is False:
                    # Not expected often, but allowed by contract.
                    self._warn(f"[reception] checkhair_available_in received False at t={get_current_time()}")
            else:
                self._warn(f"[reception] invalid availability value {avail!r} at t={get_current_time()}")

        # Process full-service completion notifications
        for token in self.input["barber_done_in"].values:
            if token != "done":
                self._warn(f"[reception] unexpected barber_done_in token {token!r} at t={get_current_time()}")
                continue
            if self.tracked_total_customers_num > 0:
                self.tracked_total_customers_num -= 1
            else:
                self.tracked_total_customers_num = 0
                self._warn(f"[reception] barber_done_in underflow protected at t={get_current_time()}")
            self._stdout_state_total_customers()

        # If we were blocked (check-in completed) and now availability is True, schedule immediate send
        if self.phase == self.PHASE_BLOCKED and self.checkhair_available and not self._pending_send:
            self._schedule_send_now()

        # Process arrivals last (after internal work precedence at same timestamp is handled by DEVS ordering)
        for token in self.input["arrival_in"].values:
            if token != "newcust":
                self._warn(f"[reception] unexpected arrival_in token {token!r} at t={get_current_time()}")
                continue

            if self.queue_count < self.capacity:
                self.queue_count += 1
                self.tracked_total_customers_num += 1
                self._stdout_state_total_customers()

                # If idle, start check-in (newly created delay must not be reduced by e)
                if self.phase == self.PHASE_IDLE:
                    self.hold_in(self.PHASE_CHECKIN, float(self.checkin_time_s))
            else:
                # Ignore completely (no stdout record)
                pass

    def lambdaf(self):
        if self.phase == self.PHASE_SEND_READY and self._pending_send:
            # DEVS output
            self.output["cust"].add("newcust")
            # External IO record at same simulation time
            self._stdout_message_send_newcust()

    def deltint(self):
        if self.phase == self.PHASE_CHECKIN:
            # Check-in completed; send only if CheckHair available, else block
            if self.checkhair_available:
                self._schedule_send_now()
            else:
                self.passivate(self.PHASE_BLOCKED)

        elif self.phase == self.PHASE_SEND_READY:
            # After sending, remove customer from reception queue (no state-change stdout for this decrement)
            if self.queue_count <= 0:
                self.queue_count = 0
                self._warn(f"[reception] attempted to send with empty queue at t={get_current_time()}")
            else:
                self.queue_count -= 1

            # Availability is consumed by sending
            self.checkhair_available = False

            # Clear pending send flag
            self._pending_send = False

            # Start next check-in immediately if queue still non-empty; else idle
            if self.queue_count > 0:
                self.hold_in(self.PHASE_CHECKIN, float(self.checkin_time_s))
            else:
                self.passivate(self.PHASE_IDLE)

        elif self.phase == self.PHASE_BLOCKED:
            # Should not have an internal event in BLOCKED; remain passive
            self.passivate(self.PHASE_BLOCKED)

        else:
            self.passivate(self.PHASE_IDLE)

    def exit(self):
        pass