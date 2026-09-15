"""Atomic DEVS model: LoadingQueue.

Responsibilities:
- Maintain FIFO queue of pallets.
- Actively expire pallets at their absolute expiration_time while queued.
- Serve FIFO claims from FleetCoordinator.
- Emit cargo availability notice when queue transitions empty->non-empty.
- Write JSONL queue events to stdout (pallet_queued, pallet_expired).
"""

import sys
import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class LoadingQueue(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Ports (locked contract)
        self.add_in_port(Port(dict, "pallet_in"))
        self.add_in_port(Port(dict, "claim_in"))
        self.add_out_port(Port(dict, "claimed_out"))
        self.add_out_port(Port(dict, "cargo_available_out"))

        # State
        self._queue: deque[dict] = deque()
        self._total_expired: int = 0

        # Output buffers for next lambdaf()
        self._pending_claimed_out: list[dict] = []
        self._pending_cargo_available_out: list[dict] = []

        # Internal event intent
        self._internal_kind: str | None = None  # "EXPIRE" or "OUTPUT"
        self._scheduled_deadline: float | None = None

    def initialize(self):
        self._queue = deque()
        self._total_expired = 0
        self._pending_claimed_out = []
        self._pending_cargo_available_out = []
        self._internal_kind = None
        self._scheduled_deadline = None
        self.passivate("IDLE")

    # ---------- helpers ----------
    def _warn(self, msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    def _log_stdout(self, record: dict) -> None:
        print(json.dumps(record), flush=True)

    def _is_valid_pallet(self, p: object) -> bool:
        if not isinstance(p, dict):
            return False
        return (
            "pallet_id" in p and "generation_time" in p and "expiration_time" in p
        )

    def _is_valid_claim(self, c: object) -> bool:
        if not isinstance(c, dict):
            return False
        return "aircraft_id" in c

    def _next_deadline(self) -> float | None:
        if not self._queue:
            return None
        try:
            return min(float(p["expiration_time"]) for p in self._queue)
        except Exception:
            # If malformed items somehow exist, ignore them for scheduling.
            deadlines = []
            for p in self._queue:
                try:
                    deadlines.append(float(p["expiration_time"]))
                except Exception:
                    continue
            return min(deadlines) if deadlines else None

    def _expire_due(self, now: float) -> None:
        """Expire all pallets with expiration_time <= now.

        Emits one stdout JSONL record per expired pallet.
        """
        if not self._queue:
            return

        kept = deque()
        for pallet in self._queue:
            try:
                exp_t = float(pallet["expiration_time"])
                pallet_id = int(pallet["pallet_id"])
            except Exception:
                # Malformed record: keep it to avoid silent data loss; warn.
                kept.append(pallet)
                self._warn(f"[LoadingQueue] Warning: malformed pallet in queue, cannot expire: {pallet!r}")
                continue

            if exp_t <= now:
                self._total_expired += 1
                self._log_stdout({
                    "time": now,
                    "entity": "queue",
                    "event": "pallet_expired",
                    "payload": {
                        "pallet_id": pallet_id,
                        "total_expired": self._total_expired,
                    },
                })
            else:
                kept.append(pallet)

        self._queue = kept

    def _reschedule(self) -> None:
        """Schedule next internal event based on pending outputs or next expiration."""
        now = get_current_time()

        if self._pending_claimed_out or self._pending_cargo_available_out:
            self._internal_kind = "OUTPUT"
            self._scheduled_deadline = None
            self.hold_in("OUTPUT", 0.0)
            return

        nd = self._next_deadline()
        if nd is None:
            self._internal_kind = None
            self._scheduled_deadline = None
            self.passivate("IDLE")
            return

        self._internal_kind = "EXPIRE"
        self._scheduled_deadline = nd
        self.hold_in("WAIT_EXPIRE", max(0.0, nd - now))

    # ---------- DEVS transitions ----------
    def deltext(self, e: float):
        now = get_current_time()

        # Confluent ordering requirement (effective):
        # 1) expire all <= now
        # 2) process pallet_in
        # 3) process claim_in
        self._expire_due(now)

        # 2) pallet_in arrivals
        for item in self.input["pallet_in"].values:
            if not self._is_valid_pallet(item):
                self._warn(f"[LoadingQueue] Warning: ignoring malformed pallet_in: {item!r}")
                continue

            try:
                pallet_id = int(item["pallet_id"])
                gen_t = float(item["generation_time"])
                exp_t = float(item["expiration_time"])
            except Exception:
                self._warn(f"[LoadingQueue] Warning: ignoring malformed pallet_in fields: {item!r}")
                continue

            # If already expired at receipt time, discard immediately and log expiration.
            if exp_t <= now:
                self._total_expired += 1
                self._log_stdout({
                    "time": now,
                    "entity": "queue",
                    "event": "pallet_expired",
                    "payload": {
                        "pallet_id": pallet_id,
                        "total_expired": self._total_expired,
                    },
                })
                continue

            was_empty = (len(self._queue) == 0)
            self._queue.append({
                "pallet_id": pallet_id,
                "generation_time": gen_t,
                "expiration_time": exp_t,
            })

            # Log queued event (stdout JSONL)
            self._log_stdout({
                "time": now,
                "entity": "queue",
                "event": "pallet_queued",
                "payload": {
                    "pallet_id": pallet_id,
                    "queue_size": len(self._queue),
                },
            })

            # Empty -> non-empty transition notice
            if was_empty:
                self._pending_cargo_available_out.append({
                    "queue_size": len(self._queue),
                })

        # 3) claim_in offers
        for claim in self.input["claim_in"].values:
            if not self._is_valid_claim(claim):
                self._warn(f"[LoadingQueue] Warning: ignoring malformed claim_in: {claim!r}")
                continue

            try:
                aircraft_id = int(claim["aircraft_id"])
            except Exception:
                self._warn(f"[LoadingQueue] Warning: ignoring malformed claim_in fields: {claim!r}")
                continue

            # Housekeeping: ensure no expired pallets remain at now
            self._expire_due(now)

            if self._queue:
                pallet = self._queue.popleft()
                try:
                    out_msg = {
                        "aircraft_id": aircraft_id,
                        "pallet_id": int(pallet["pallet_id"]),
                        "generation_time": float(pallet["generation_time"]),
                    }
                except Exception:
                    # If somehow malformed, drop it and warn; do not emit claimed_out.
                    self._warn(f"[LoadingQueue] Warning: malformed pallet claimed from queue, dropping: {pallet!r}")
                else:
                    self._pending_claimed_out.append(out_msg)
            # else: emit no claimed_out

        # Schedule next internal event (output flush or next expiration or passive)
        self._reschedule()

    def lambdaf(self):
        if self.phase != "OUTPUT":
            return

        # Emit DEVS outputs only here.
        for msg in self._pending_cargo_available_out:
            self.output["cargo_available_out"].add(dict(msg))
        for msg in self._pending_claimed_out:
            self.output["claimed_out"].add(dict(msg))

    def deltint(self):
        now = get_current_time()

        if self.phase == "OUTPUT":
            self._pending_cargo_available_out = []
            self._pending_claimed_out = []
            self._internal_kind = None
            self._scheduled_deadline = None
            self._reschedule()
            return

        if self.phase == "WAIT_EXPIRE":
            # Expire all pallets due at now (including any <= now)
            self._expire_due(now)
            self._internal_kind = None
            self._scheduled_deadline = None
            self._reschedule()
            return

        # Fallback: passivate
        self._internal_kind = None
        self._scheduled_deadline = None
        self.passivate("IDLE")

    def exit(self):
        pass