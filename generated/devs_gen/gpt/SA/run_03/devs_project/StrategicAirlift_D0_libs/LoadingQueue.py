import json
import sys
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class LoadingQueue(Atomic):
    """
    Atomic DEVS FIFO buffer that owns unassigned pallets and enforces their absolute deadlines
    while they remain in the queue.

    Inputs:
      - pallet_in: {'pallet_id': int, 'generation_time': float, 'expiration_time': float}
      - claim_request_in: {'aircraft_id': int}

    Outputs:
      - claimed_pallet_out: {'aircraft_id': int, 'pallet_id': int, 'generation_time': float}

    External IO (stdout JSONL only):
      - pallet_queued
      - pallet_expired
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "pallet_in"))
        self.add_in_port(Port(dict, "claim_request_in"))
        self.add_out_port(Port(dict, "claimed_pallet_out"))

        # State
        self.queue: deque[dict] = deque()
        self.total_expired: int = 0

        # Prepared outputs for next lambdaf()
        self._prepared_claims: list[dict] = []

        # Internal scheduling
        self._next_expiration_time: float = float("inf")
        self._internal_time: float = float("inf")  # absolute time of next internal event, if any

    def initialize(self):
        self.queue = deque()
        self.total_expired = 0
        self._prepared_claims = []
        self._next_expiration_time = float("inf")
        self._internal_time = float("inf")
        self.passivate("PASSIVE")

    @staticmethod
    def _stdout_event(record: dict) -> None:
        # Must not write any non-event text to stdout.
        print(json.dumps(record), flush=True)

    def _recompute_next_expiration(self) -> None:
        if not self.queue:
            self._next_expiration_time = float("inf")
            return
        self._next_expiration_time = min(float(p["expiration_time"]) for p in self.queue)

    def _schedule_from_now(self, now: float) -> None:
        """
        Schedule the next internal event based on current queue contents.
        Uses absolute next expiration time; converts to sigma relative to now.
        """
        self._recompute_next_expiration()

        if self._next_expiration_time == float("inf"):
            self._internal_time = float("inf")
            self.passivate("PASSIVE")
            return

        self._internal_time = float(self._next_expiration_time)
        sigma = max(0.0, self._internal_time - now)
        self.hold_in("EXPIRING", sigma)

    def _expire_due_at(self, t: float) -> None:
        """
        Expire every pallet still in the queue whose expiration_time == t.
        Emits stdout JSONL records exactly at time t (using get_current_time()).
        """
        # Remove all due pallets; preserve FIFO order among non-due.
        remaining = deque()
        due = []
        for p in self.queue:
            if float(p["expiration_time"]) == t:
                due.append(p)
            else:
                remaining.append(p)
        self.queue = remaining

        for p in due:
            self.total_expired += 1
            self._stdout_event({
                "time": get_current_time(),
                "entity": "queue",
                "event": "pallet_expired",
                "payload": {
                    "pallet_id": int(p["pallet_id"]),
                    "total_expired": int(self.total_expired),
                },
            })

    def _expire_at_or_before_now(self, now: float) -> None:
        """
        Treat any pallets with expiration_time <= now as expired at now.
        This is required before processing claim requests at time now.
        """
        if not self.queue:
            return

        remaining = deque()
        expired_now = []
        for p in self.queue:
            if float(p["expiration_time"]) <= now:
                expired_now.append(p)
            else:
                remaining.append(p)
        self.queue = remaining

        for p in expired_now:
            self.total_expired += 1
            self._stdout_event({
                "time": get_current_time(),
                "entity": "queue",
                "event": "pallet_expired",
                "payload": {
                    "pallet_id": int(p["pallet_id"]),
                    "total_expired": int(self.total_expired),
                },
            })

    def deltext(self, e: float):
        # If an internal event is already scheduled, preserve remaining time unless we reschedule.
        now = float(get_current_time())

        # Collect inputs (may receive both ports at same simulation time).
        pallets = [dict(p) for p in self.input["pallet_in"].values]
        claims = [dict(r) for r in self.input["claim_request_in"].values]

        # Enqueue pallets and log immediately.
        for p in pallets:
            self.queue.append(p)
            self._stdout_event({
                "time": now,
                "entity": "queue",
                "event": "pallet_queued",
                "payload": {
                    "pallet_id": int(p["pallet_id"]),
                    "queue_size": int(len(self.queue)),
                },
            })

        # Process claim requests sequentially in a deterministic order (arrival order in bag).
        # Before selecting a pallet, expire any with expiration_time <= now.
        if claims:
            self._expire_at_or_before_now(now)

            for req in claims:
                if not self.queue:
                    continue
                offered_aircraft_id = int(req["aircraft_id"])
                pallet = self.queue.popleft()
                self._prepared_claims.append({
                    "aircraft_id": offered_aircraft_id,
                    "pallet_id": int(pallet["pallet_id"]),
                    "generation_time": float(pallet["generation_time"]),
                })

        # After processing all inputs at this time, recompute and schedule next expiration.
        # If the minimum expiration equals now (including already-expired arrivals), schedule immediate.
        self._schedule_from_now(now)

        # If we have prepared claims, ensure an immediate output event occurs.
        # This does not change stdout ordering constraints (claims produce no stdout here).
        if self._prepared_claims:
            self.hold_in("OUTPUT_READY", 0.0)

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return

        # Emit all prepared claim outputs (one per successful claim).
        for msg in self._prepared_claims:
            self.output["claimed_pallet_out"].add(dict(msg))

    def deltint(self):
        now = float(get_current_time())

        if self.phase == "OUTPUT_READY":
            # Clear prepared claims and then schedule expirations based on current queue.
            self._prepared_claims = []
            self._schedule_from_now(now)
            return

        if self.phase == "EXPIRING":
            # Internal expiration event at the earliest expiration time among queued pallets.
            t = float(self._internal_time)
            # Ensure we are expiring exactly those with expiration_time == t.
            self._expire_due_at(t)
            # Schedule next expiration or passivate.
            self._schedule_from_now(now)
            return

        # Fallback: become passive.
        self.passivate("PASSIVE")

    def exit(self):
        # No final summary required.
        pass