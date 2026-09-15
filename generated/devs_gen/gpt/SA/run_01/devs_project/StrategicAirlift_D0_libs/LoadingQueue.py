import json
import sys
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class LoadingQueue(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Ports (locked contract)
        self.add_in_port(Port(dict, "pallet_in"))
        self.add_in_port(Port(dict, "claim_request_in"))
        self.add_out_port(Port(dict, "cargo_available_out"))
        self.add_out_port(Port(dict, "claimed_pallet_out"))

        # Remembered state
        self.queue: deque[dict] = deque()
        self.total_expired: int = 0

        # Output preparation (emitted only in lambdaf)
        self._pending_cargo_available: dict | None = None
        self._pending_claimed: dict | None = None

    # ---------- helpers ----------
    def _stdout_event(self, record: dict) -> None:
        print(json.dumps(record), flush=True)

    def _warn(self, msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    def _earliest_expiration_time(self) -> float | None:
        if not self.queue:
            return None
        # O(n) scan; queue is unbounded but typically modest. Keeps interface simple.
        return min(float(p["expiration_time"]) for p in self.queue)

    def _schedule_next_expiration(self) -> None:
        now = float(get_current_time())
        next_t = self._earliest_expiration_time()
        if next_t is None:
            self.passivate("WAITING")
            return
        sigma = max(0.0, float(next_t) - now)
        self.hold_in("EXPIRATION_DUE", sigma)

    def _discard_expired_at_time(self, t_now: float) -> bool:
        """Discard all pallets with expiration_time == t_now. Return True if queue size changed."""
        if not self.queue:
            return False

        changed = False
        kept = deque()
        for pallet in self.queue:
            exp_t = float(pallet["expiration_time"])
            if exp_t == t_now:
                changed = True
                self.total_expired += 1
                self._stdout_event(
                    {
                        "time": t_now,
                        "entity": "queue",
                        "event": "pallet_expired",
                        "payload": {
                            "pallet_id": int(pallet["pallet_id"]),
                            "total_expired": int(self.total_expired),
                        },
                    }
                )
            else:
                kept.append(pallet)

        self.queue = kept
        return changed

    def _prepare_cargo_available(self) -> None:
        self._pending_cargo_available = {"queue_size": int(len(self.queue))}

    def _enter_output_ready(self) -> None:
        # Ensure outputs happen only from lambdaf.
        self.hold_in("OUTPUT_READY", 0.0)

    # ---------- DEVS lifecycle ----------
    def initialize(self):
        self.queue = deque()
        self.total_expired = 0
        self._pending_cargo_available = None
        self._pending_claimed = None
        self.passivate("WAITING")

    def deltext(self, e: float):
        # If we're already scheduled to output, do not change anything here.
        if self.phase == "OUTPUT_READY":
            self.continuef(e)
            return

        # If an expiration internal is pending at the same time, default DEVS confluent
        # will run deltcon; we keep default deltcon behavior as required.

        t_now = float(get_current_time())

        # Process incoming pallets
        for pallet in self.input["pallet_in"].values:
            p = dict(pallet)
            # Enqueue first (even if exp == now or exp < now)
            self.queue.append(p)

            # stdout pallet_queued immediately at t_now
            self._stdout_event(
                {
                    "time": t_now,
                    "entity": "queue",
                    "event": "pallet_queued",
                    "payload": {
                        "pallet_id": int(p["pallet_id"]),
                        "queue_size": int(len(self.queue)),
                    },
                }
            )

            # DEVS output cargo_available_out immediately at t_now
            self._prepare_cargo_available()
            self._enter_output_ready()

            # Late/invalid expiration_time handling: treat as immediately expired at t_now
            exp_t = float(p.get("expiration_time"))
            if exp_t < t_now:
                self._warn(
                    f"[LoadingQueue] Warning: received pallet_id={p.get('pallet_id')} with "
                    f"expiration_time={exp_t} < now={t_now}; expiring immediately."
                )
                # Discard those with expiration_time == t_now only per rule,
                # but for exp_t < t_now we must also expire at t_now.
                # Implement by setting its expiration_time to t_now for accounting consistency.
                p["expiration_time"] = t_now

        # Process claim requests
        for req in self.input["claim_request_in"].values:
            aircraft_id = int(req["aircraft_id"])

            # Respect expiration at exactly t_now before claiming
            changed_by_exp = self._discard_expired_at_time(t_now)

            # Find earliest eligible pallet: FIFO with expiration_time > t_now
            claimed = None
            if self.queue:
                # FIFO scan; remove first eligible
                new_q = deque()
                removed = False
                for pallet in self.queue:
                    if (not removed) and float(pallet["expiration_time"]) > t_now:
                        claimed = pallet
                        removed = True
                        continue
                    new_q.append(pallet)
                if removed:
                    self.queue = new_q

            if claimed is not None:
                self._pending_claimed = {
                    "aircraft_id": aircraft_id,
                    "pallet_id": int(claimed["pallet_id"]),
                    "generation_time": float(claimed["generation_time"]),
                }
                # Refresh coordinator view if queue size changed due to removal or expirations
                if changed_by_exp or True:
                    # removal always changes size; changed_by_exp may or may not
                    self._prepare_cargo_available()
                self._enter_output_ready()
            else:
                if changed_by_exp:
                    self._prepare_cargo_available()
                    self._enter_output_ready()
                else:
                    self._warn(
                        f"[LoadingQueue] Claim request for aircraft_id={aircraft_id} at t={t_now} "
                        f"but no eligible pallet available."
                    )

        # If we scheduled OUTPUT_READY, do not schedule expiration now; deltint will do it.
        if self.phase == "OUTPUT_READY":
            return

        # Otherwise, update expiration monitoring schedule
        self._schedule_next_expiration()

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return

        if self._pending_claimed is not None:
            self.output["claimed_pallet_out"].add(dict(self._pending_claimed))

        if self._pending_cargo_available is not None:
            self.output["cargo_available_out"].add(dict(self._pending_cargo_available))

    def deltint(self):
        if self.phase == "OUTPUT_READY":
            self._pending_claimed = None
            self._pending_cargo_available = None
            self._schedule_next_expiration()
            return

        if self.phase == "EXPIRATION_DUE":
            t_now = float(get_current_time())
            before = len(self.queue)
            changed = self._discard_expired_at_time(t_now)
            after = len(self.queue)

            if changed and before != after:
                self._prepare_cargo_available()
                self._enter_output_ready()
                return

            self._schedule_next_expiration()
            return

        # Fallback: remain waiting
        self.passivate("WAITING")

    def exit(self):
        pass