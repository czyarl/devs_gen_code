"""FleetCoordinator: reactive atomic dispatcher coordinating aircraft and loading queue.

Implements a two-step FIFO handshake:
1) Receive idle aircraft notices, maintain FIFO-ordered idle pool (no duplicates).
2) When possible, emit one claim_request_out for exactly one idle aircraft at a time.
3) Upon claimed_pallet_in, emit assignment_out and write assignment_created JSONL to stdout.
"""

import sys
import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class FleetCoordinator(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Ports (locked contract)
        self.add_in_port(Port(dict, "aircraft_idle_in"))
        self.add_in_port(Port(dict, "claimed_pallet_in"))
        self.add_out_port(Port(dict, "claim_request_out"))
        self.add_out_port(Port(dict, "assignment_out"))

        # State (initialized in initialize())
        self.idle_pool_order: deque[int] = deque()
        self.idle_pool_set: set[int] = set()
        self.inflight_claim: int | None = None  # at most one outstanding claim

        # Pending outputs for next internal firing at current sim time
        self.pending_claim_request: dict | None = None
        self.pending_assignment: dict | None = None

        # Stdout monotonicity guard
        self.last_stdout_time: float | None = None

    def initialize(self):
        self.idle_pool_order = deque()
        self.idle_pool_set = set()
        self.inflight_claim = None

        self.pending_claim_request = None
        self.pending_assignment = None

        self.last_stdout_time = None

        # Passive at initialization; no autonomous internal events.
        self.passivate("WAITING")

    def _warn(self, msg: str) -> None:
        print(f"[FleetCoordinator:{self.name}] {msg}", file=sys.stderr, flush=True)

    def _enqueue_idle_aircraft(self, aircraft_id: int) -> None:
        # Do not enqueue duplicates; treat as set while preserving FIFO order.
        if self.inflight_claim == aircraft_id:
            # Ignore idle notice while claim is in-flight.
            self._warn(f"Received aircraft_idle_in for aircraft_id={aircraft_id} while inflight claim exists; ignoring.")
            return
        if aircraft_id in self.idle_pool_set:
            return
        self.idle_pool_order.append(aircraft_id)
        self.idle_pool_set.add(aircraft_id)

    def _remove_from_idle_pool(self, aircraft_id: int) -> None:
        if aircraft_id not in self.idle_pool_set:
            return
        self.idle_pool_set.discard(aircraft_id)
        # Remove from deque (may be small; deterministic behavior is more important than O(n))
        new_q: deque[int] = deque()
        for aid in self.idle_pool_order:
            if aid != aircraft_id:
                new_q.append(aid)
        self.idle_pool_order = new_q

    def _select_next_idle_aircraft(self) -> int | None:
        while self.idle_pool_order:
            aid = self.idle_pool_order[0]
            if aid in self.idle_pool_set:
                return aid
            self.idle_pool_order.popleft()
        return None

    def _stage_claim_if_possible(self) -> None:
        # Respect at most one outstanding claim at a time.
        if self.inflight_claim is not None:
            return
        if self.pending_claim_request is not None:
            return
        aid = self._select_next_idle_aircraft()
        if aid is None:
            return

        # Remove from idle pool when we start the claim handshake to prevent reuse.
        self._remove_from_idle_pool(aid)
        self.inflight_claim = aid
        self.pending_claim_request = {"aircraft_id": aid}

    def _schedule_output_if_needed(self) -> None:
        if self.pending_claim_request is not None or self.pending_assignment is not None:
            self.hold_in("OUTPUT_READY", 0.0)
        else:
            self.passivate("WAITING")

    def deltext(self, e: float):
        # If an internal output is already scheduled at this same time, keep it.
        if self.phase == "OUTPUT_READY":
            self.continuef(e)
            return

        # Process all inputs at this simulation time.
        for msg in self.input["aircraft_idle_in"].values:
            try:
                aircraft_id = int(msg["aircraft_id"])
            except Exception as ex:
                self._warn(f"Malformed aircraft_idle_in message {msg!r}: {ex}")
                continue
            self._enqueue_idle_aircraft(aircraft_id)

        for msg in self.input["claimed_pallet_in"].values:
            # Expected: {'aircraft_id': int, 'pallet_id': int, 'generation_time': float}
            try:
                aircraft_id = int(msg["aircraft_id"])
                pallet_id = int(msg["pallet_id"])
                generation_time = float(msg["generation_time"])
            except Exception as ex:
                self._warn(f"Malformed claimed_pallet_in message {msg!r}: {ex}")
                continue

            if self.inflight_claim != aircraft_id:
                # Unexpected/late/duplicate: honor but warn.
                self._warn(
                    f"claimed_pallet_in for aircraft_id={aircraft_id} but inflight_claim={self.inflight_claim}; honoring anyway."
                )

            # Clear inflight claim if it matches; otherwise clear anyway to avoid deadlock.
            if self.inflight_claim == aircraft_id or self.inflight_claim is None:
                self.inflight_claim = None
            else:
                # Different inflight claim exists; clear it to avoid permanent blockage (cannot disambiguate further).
                self._warn(
                    f"Clearing inflight_claim={self.inflight_claim} due to unexpected claimed_pallet_in for aircraft_id={aircraft_id}."
                )
                self.inflight_claim = None

            # Aircraft is now assigned; ensure it is not idle.
            self._remove_from_idle_pool(aircraft_id)

            # Prepare assignment (broadcast)
            self.pending_assignment = {
                "aircraft_id": aircraft_id,
                "pallet_id": pallet_id,
                "generation_time": generation_time,
            }

            # Log assignment_created at the same absolute simulation time as assignment_out emission.
            now = float(get_current_time())
            if self.last_stdout_time is not None and now < self.last_stdout_time:
                self._warn(
                    f"Nondecreasing stdout time violated (now={now} < last={self.last_stdout_time}); clamping to last."
                )
                now = self.last_stdout_time
            record = {
                "time": now,
                "entity": "coordinator",
                "event": "assignment_created",
                "payload": {"aircraft_id": aircraft_id, "pallet_id": pallet_id},
            }
            print(json.dumps(record), flush=True)
            self.last_stdout_time = now

        # After processing inputs, try to stage at most one claim request.
        # This can chain after an assignment in the same time instant.
        self._stage_claim_if_possible()
        self._schedule_output_if_needed()

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return

        if self.pending_assignment is not None:
            self.output["assignment_out"].add(dict(self.pending_assignment))

        if self.pending_claim_request is not None:
            self.output["claim_request_out"].add(dict(self.pending_claim_request))

    def deltint(self):
        if self.phase != "OUTPUT_READY":
            self.passivate("WAITING")
            return

        # Clear emitted outputs
        self.pending_assignment = None
        self.pending_claim_request = None

        # If more idle aircraft exist and no inflight claim, we can immediately request again.
        self._stage_claim_if_possible()
        self._schedule_output_if_needed()

    def exit(self):
        pass