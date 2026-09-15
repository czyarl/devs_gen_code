"""FleetCoordinator: reactive atomic dispatcher coordinating aircraft and cargo via claim/claimed handshake."""

import sys
import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class FleetCoordinator(Atomic):
    """
    Reactive dispatcher that matches idle aircraft with queued cargo using a two-step handshake.

    Ports (locked contract):
    Inputs:
      - aircraft_idle_in: {'aircraft_id': int}
      - cargo_available_in: {'queue_size': int}
      - claimed_in: {'aircraft_id': int, 'pallet_id': int, 'generation_time': float}
    Outputs:
      - claim_out: {'aircraft_id': int}
      - assignment_out: {'aircraft_id': int, 'pallet_id': int, 'generation_time': float}

    External IO:
      - stdout JSONL per assignment_created at the simulation time of assignment creation.
      - optional warnings to stderr (non-JSONL).
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Ports
        self.add_in_port(Port(dict, "aircraft_idle_in"))
        self.add_in_port(Port(dict, "cargo_available_in"))
        self.add_in_port(Port(dict, "claimed_in"))

        self.add_out_port(Port(dict, "claim_out"))
        self.add_out_port(Port(dict, "assignment_out"))

        # Remembered state
        self.idle_aircraft: deque[int] = deque()
        self.idle_set: set[int] = set()
        self.cargo_hint_available: bool = False
        self.pending_claims: set[int] = set()

        # Prepared outputs for zero-delay emission
        self._prepared_claims: list[dict] = []
        self._prepared_assignments: list[dict] = []
        self._prepared_stdout_records: list[dict] = []

    def initialize(self):
        # Passive at initialization; no autonomous outputs.
        self.idle_aircraft = deque()
        self.idle_set = set()
        self.cargo_hint_available = False
        self.pending_claims = set()

        self._prepared_claims = []
        self._prepared_assignments = []
        self._prepared_stdout_records = []

        self.passivate("PASSIVE")

    def _remove_from_idle_queue_if_present(self, aircraft_id: int) -> None:
        """Best-effort removal to handle duplicates/races; preserves relative order of others."""
        if not self.idle_aircraft:
            return
        if aircraft_id not in self.idle_aircraft:
            return
        self.idle_aircraft = deque(a for a in self.idle_aircraft if a != aircraft_id)

    def _initiate_claims_if_possible(self) -> None:
        """Prepare as many claim_out messages as possible at current time."""
        if not self.cargo_hint_available:
            return

        while self.idle_aircraft:
            aircraft_id = self.idle_aircraft[0]
            if aircraft_id in self.pending_claims:
                # Should not happen (we avoid enqueueing), but be robust.
                self.idle_aircraft.popleft()
                self.idle_set.discard(aircraft_id)
                continue

            aircraft_id = self.idle_aircraft.popleft()
            self.idle_set.discard(aircraft_id)
            self.pending_claims.add(aircraft_id)
            self._prepared_claims.append({"aircraft_id": aircraft_id})

    def _schedule_output_if_any(self, e: float) -> None:
        """Schedule immediate output if there are prepared messages; otherwise remain/passivate."""
        if self._prepared_claims or self._prepared_assignments:
            self.hold_in("OUTPUT_READY", 0.0)
        else:
            # Preserve remaining time if we were active; otherwise stay passive.
            if self.phase == "OUTPUT_READY":
                self.continuef(e)
            else:
                self.passivate("PASSIVE")

    def deltext(self, e: float):
        # If an internal output is already scheduled, do not change it; just preserve time.
        if self.phase == "OUTPUT_READY":
            self.continuef(e)
            return

        # Process aircraft idle notifications
        for msg in self.input["aircraft_idle_in"].values:
            try:
                aircraft_id = int(msg["aircraft_id"])
            except Exception:
                print(f"WARNING FleetCoordinator: invalid aircraft_idle_in message: {msg}", file=sys.stderr, flush=True)
                continue

            if aircraft_id in self.idle_set or aircraft_id in self.pending_claims:
                continue
            self.idle_aircraft.append(aircraft_id)
            self.idle_set.add(aircraft_id)

        # Process cargo availability hints
        for msg in self.input["cargo_available_in"].values:
            try:
                queue_size = int(msg["queue_size"])
            except Exception:
                print(f"WARNING FleetCoordinator: invalid cargo_available_in message: {msg}", file=sys.stderr, flush=True)
                continue
            self.cargo_hint_available = queue_size > 0

        # Process claimed pallets (creates assignments)
        for msg in self.input["claimed_in"].values:
            try:
                aircraft_id = int(msg["aircraft_id"])
                pallet_id = int(msg["pallet_id"])
                generation_time = float(msg["generation_time"])
            except Exception:
                print(f"WARNING FleetCoordinator: invalid claimed_in message: {msg}", file=sys.stderr, flush=True)
                continue

            if aircraft_id in self.pending_claims:
                self.pending_claims.remove(aircraft_id)
            else:
                # Still forward assignment to avoid dropping cargo, per contract.
                print(
                    f"WARNING FleetCoordinator: claimed_in for aircraft_id={aircraft_id} not in pending_claims",
                    file=sys.stderr,
                    flush=True,
                )

            # Ensure aircraft is not considered idle anymore.
            self.idle_set.discard(aircraft_id)
            self._remove_from_idle_queue_if_present(aircraft_id)

            assignment = {
                "aircraft_id": aircraft_id,
                "pallet_id": pallet_id,
                "generation_time": generation_time,
            }
            self._prepared_assignments.append(assignment)

            t = float(get_current_time())
            self._prepared_stdout_records.append({
                "time": t,
                "entity": "coordinator",
                "event": "assignment_created",
                "payload": {"aircraft_id": aircraft_id, "pallet_id": pallet_id},
            })

        # After processing all inputs at time t, attempt to initiate claims.
        self._initiate_claims_if_possible()

        # Schedule immediate output if needed.
        self._schedule_output_if_any(e)

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return

        # Emit all prepared claim requests (may be multiple at same simulation time).
        for claim in self._prepared_claims:
            self.output["claim_out"].add(dict(claim))

        # Emit all prepared assignments and corresponding stdout JSONL records.
        for assignment in self._prepared_assignments:
            self.output["assignment_out"].add(dict(assignment))

        for record in self._prepared_stdout_records:
            print(json.dumps(record), flush=True)

    def deltint(self):
        # Clear prepared outputs after emission.
        self._prepared_claims = []
        self._prepared_assignments = []
        self._prepared_stdout_records = []

        # No autonomous internal behavior; wait for next input.
        self.passivate("PASSIVE")

    def exit(self):
        # No final report beyond per-assignment JSONL records.
        pass