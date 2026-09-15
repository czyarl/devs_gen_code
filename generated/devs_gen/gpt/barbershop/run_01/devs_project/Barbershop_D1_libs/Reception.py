import json
import sys
from collections import deque

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Reception(Atomic):
    def __init__(self, name: str, parent: Coupled | None, queue_capacity: int, checkin_time_s: float):
        super().__init__(name)
        self.parent = parent

        # Parameters (fixed by scenario, but passed in by runner per contract)
        self.queue_capacity = int(queue_capacity)
        self.checkin_time_s = float(checkin_time_s)

        # Ports
        self.add_in_port(Port(str, "arrival_in"))
        self.add_in_port(Port(str, "service_done_in"))
        self.add_in_port(Port(bool, "checkhair_available_in"))
        self.add_out_port(Port(str, "cust"))

        # State (initialized in initialize)
        self.queue: deque[object] = deque()
        self.total_customers_num: int = 0
        self.checking_in: bool = False
        self.checkin_deadline_time: float | None = None
        self.pending_handoff: bool = False
        self.checkhair_available: bool = False

        # Output latch for DEVS port emission
        self._cust_to_send: str | None = None

    # ---------- JSONL writers (stdout only for required records) ----------
    def _emit_state_if_changed(self, t: float, old: int, new: int) -> None:
        if new == old:
            return
        print(
            json.dumps(
                {
                    "time": float(t),
                    "type": "state",
                    "model": "reception",
                    "field": "total customers num",
                    "value": int(new),
                }
            ),
            flush=True,
        )

    def _emit_message_cust(self, t: float) -> None:
        print(
            json.dumps(
                {
                    "time": float(t),
                    "type": "message",
                    "model": "reception",
                    "port": "cust",
                    "content": "newcust",
                }
            ),
            flush=True,
        )

    # ---------- Helpers ----------
    def _start_checkin(self, now: float) -> None:
        # Preconditions: queue nonempty, not checking_in, not pending_handoff
        self.checking_in = True
        self.checkin_deadline_time = float(now) + self.checkin_time_s
        self.hold_in("CHECKIN", self.checkin_time_s)

    def _schedule_immediate_handoff(self) -> None:
        # Schedule a zero-delay internal to perform output in lambdaf.
        self.hold_in("HANDOFF", 0.0)

    def _perform_handoff_prepare_output(self, now: float) -> None:
        # Preconditions: queue nonempty, checkhair_available True
        # Prepare DEVS output and stdout message record.
        self._cust_to_send = "newcust"
        self._emit_message_cust(now)

        # Dequeue exactly one customer
        if self.queue:
            self.queue.popleft()
        else:
            print(
                f"WARNING: reception handoff attempted with empty queue at t={now}",
                file=sys.stderr,
                flush=True,
            )

    # ---------- DEVS lifecycle ----------
    def initialize(self):
        self.queue = deque()
        self.total_customers_num = 0
        self.checking_in = False
        self.checkin_deadline_time = None
        self.pending_handoff = False
        self.checkhair_available = False
        self._cust_to_send = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        # Preserve remaining time if already scheduled.
        if self.phase != "IDLE":
            self.continuef(e)

        now = get_current_time()

        # Process availability updates first so they can trigger immediate handoff at same t.
        for avail in self.input["checkhair_available_in"].values:
            if isinstance(avail, bool):
                self.checkhair_available = avail
            else:
                # Port is typed bool; still be defensive.
                self.checkhair_available = bool(avail)

            if self.checkhair_available and self.pending_handoff:
                # Immediate handoff at same simulation time
                self._schedule_immediate_handoff()

        # Process service done notifications.
        for msg in self.input["service_done_in"].values:
            if msg != "done":
                print(
                    f"WARNING: reception received unexpected service_done_in payload={msg!r} at t={now}",
                    file=sys.stderr,
                    flush=True,
                )
                continue
            old = self.total_customers_num
            if self.total_customers_num > 0:
                self.total_customers_num -= 1
            else:
                print(
                    f"WARNING: reception total customers num already 0 on done at t={now}; clamping to 0",
                    file=sys.stderr,
                    flush=True,
                )
                self.total_customers_num = 0
            self._emit_state_if_changed(now, old, self.total_customers_num)

        # Process arrivals.
        for payload in self.input["arrival_in"].values:
            if payload != "newcust":
                print(
                    f"WARNING: reception ignoring unexpected arrival_in payload={payload!r} at t={now}",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            if len(self.queue) < self.queue_capacity:
                self.queue.append(object())
                old = self.total_customers_num
                self.total_customers_num += 1
                self._emit_state_if_changed(now, old, self.total_customers_num)

                # Start check-in if idle and no pending handoff.
                if (not self.checking_in) and (not self.pending_handoff):
                    self._start_checkin(now)
            else:
                # Drop if at capacity; no log.
                pass

        # If we were active and no new scheduling happened, ensure we keep current schedule.
        # continuef(e) already preserved it. If we were IDLE and nothing scheduled, remain IDLE.
        if self.phase == "IDLE":
            # If an immediate handoff was scheduled, phase is not IDLE anymore.
            pass

    def lambdaf(self):
        if self.phase == "HANDOFF" and self._cust_to_send is not None:
            self.output["cust"].add(self._cust_to_send)

    def deltint(self):
        now = get_current_time()

        if self.phase == "CHECKIN":
            # Check-in completion
            self.checking_in = False
            self.checkin_deadline_time = None

            if self.checkhair_available:
                # Handoff immediately at this same time
                self._perform_handoff_prepare_output(now)
                # After output, decide next action in next internal (HANDOFF phase)
                self.hold_in("HANDOFF", 0.0)
            else:
                # Can't handoff yet; latch pending
                self.pending_handoff = True
                self.passivate("IDLE")

        elif self.phase == "HANDOFF":
            # Complete the handoff transition after lambdaf sent the port output.
            self._cust_to_send = None

            # If this HANDOFF was due to pending_handoff, clear it.
            if self.pending_handoff and self.checkhair_available:
                self.pending_handoff = False

            # If queue still has customers, start next check-in
            if self.queue:
                self._start_checkin(now)
            else:
                self.passivate("IDLE")

        else:
            self.passivate("IDLE")

    def exit(self):
        pass