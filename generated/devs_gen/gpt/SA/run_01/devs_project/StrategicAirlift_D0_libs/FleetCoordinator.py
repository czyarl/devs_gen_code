"""FleetCoordinator: match idle aircraft to queued cargo via claim/assign handshake."""

import json
import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class FleetCoordinator(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Inputs
        self.add_in_port(Port(dict, "aircraft_idle_in"))
        self.add_in_port(Port(dict, "cargo_available_in"))
        self.add_in_port(Port(dict, "claimed_pallet_in"))

        # Outputs
        self.add_out_port(Port(dict, "claim_request_out"))
        self.add_out_port(Port(dict, "assignment_out"))

        # Remembered state (initialized in initialize()).
        self.idle_aircraft = set()
        self.cargo_known_available = False
        self.last_reported_queue_size = 0
        self.inflight_claims = set()
        self.last_stdout_time = float("-inf")

        # Prepared outputs for lambdaf()
        self._prepared_claim_requests = []
        self._prepared_assignments = []

        # Duplicate suppression for claimed_pallet_in
        self._seen_claimed_msgs = set()  # tuples: (time, aircraft_id, pallet_id)

    def initialize(self):
        self.idle_aircraft = set()
        self.cargo_known_available = False
        self.last_reported_queue_size = 0
        self.inflight_claims = set()
        self.last_stdout_time = float("-inf")

        self._prepared_claim_requests = []
        self._prepared_assignments = []
        self._seen_claimed_msgs = set()

        # Passive at initialization: no outputs until inputs arrive.
        self.passivate("WAITING")

    def _warn(self, msg: str) -> None:
        print(f"[FleetCoordinator] {msg}", file=sys.stderr, flush=True)

    def _log_assignment_created(self, t: float, aircraft_id: int, pallet_id: int) -> None:
        if t < self.last_stdout_time:
            # Defensive: never emit out of time order
            self._warn(
                f"stdout time order violation avoided: attempted to log time={t} "
                f"after last_stdout_time={self.last_stdout_time}"
            )
            t = self.last_stdout_time

        record = {
            "time": float(t),
            "entity": "coordinator",
            "event": "assignment_created",
            "payload": {"aircraft_id": int(aircraft_id), "pallet_id": int(pallet_id)},
        }
        print(json.dumps(record), flush=True)
        self.last_stdout_time = float(t)

    def _prepare_claim_requests(self) -> None:
        """Prepare as many claim requests as possible at current time."""
        if not self.cargo_known_available:
            return

        eligible = sorted(aid for aid in self.idle_aircraft if aid not in self.inflight_claims)
        if not eligible:
            return

        # If queue_size is known, do not exceed it; otherwise be conservative.
        if self.last_reported_queue_size > 0:
            max_to_issue = min(len(eligible), int(self.last_reported_queue_size))
        else:
            # cargo_known_available True but queue_size unknown/0: issue one conservatively
            max_to_issue = 1

        for aid in eligible[:max_to_issue]:
            self._prepared_claim_requests.append({"aircraft_id": int(aid)})
            self.inflight_claims.add(int(aid))

    def _schedule_outputs_if_any(self) -> None:
        if self._prepared_claim_requests or self._prepared_assignments:
            self.hold_in("OUTPUT_READY", 0.0)
        else:
            self.passivate("WAITING")

    def deltext(self, e: float):
        # If an internal output is already scheduled, do not change prepared outputs.
        if self.phase == "OUTPUT_READY":
            self.continuef(e)
            return

        # Process all inputs in the current message bag.
        for msg in self.input["aircraft_idle_in"].values:
            try:
                aircraft_id = int(msg["aircraft_id"])
            except Exception:
                self._warn(f"invalid aircraft_idle_in message ignored: {msg!r}")
                continue
            self.idle_aircraft.add(aircraft_id)
            # Preferred: do NOT clear inflight_claims on idle notice.

        for msg in self.input["cargo_available_in"].values:
            try:
                queue_size = int(msg["queue_size"])
            except Exception:
                self._warn(f"invalid cargo_available_in message ignored: {msg!r}")
                continue
            self.last_reported_queue_size = queue_size
            self.cargo_known_available = queue_size > 0

        now = float(get_current_time())
        for msg in self.input["claimed_pallet_in"].values:
            # Validate and parse
            try:
                aircraft_id = int(msg["aircraft_id"])
                pallet_id = int(msg["pallet_id"])
                generation_time = float(msg["generation_time"])
            except Exception:
                self._warn(f"invalid claimed_pallet_in message ignored: {msg!r}")
                continue

            key = (now, aircraft_id, pallet_id)
            if key in self._seen_claimed_msgs:
                self._warn(
                    f"duplicate claimed_pallet_in ignored at time={now}: "
                    f"(aircraft_id={aircraft_id}, pallet_id={pallet_id})"
                )
                continue
            self._seen_claimed_msgs.add(key)

            if aircraft_id not in self.idle_aircraft:
                self._warn(
                    f"claimed_pallet_in for non-idle aircraft at time={now}: "
                    f"aircraft_id={aircraft_id}, pallet_id={pallet_id}"
                )
            else:
                self.idle_aircraft.remove(aircraft_id)

            if aircraft_id in self.inflight_claims:
                self.inflight_claims.remove(aircraft_id)

            assignment = {
                "aircraft_id": aircraft_id,
                "pallet_id": pallet_id,
                "generation_time": generation_time,
            }
            self._prepared_assignments.append(assignment)

            # External IO: stdout JSONL at assignment creation time.
            self._log_assignment_created(now, aircraft_id, pallet_id)

        # After updating state, attempt to initiate claim(s).
        # Edge case: if queue_size==0, cargo_known_available False prevents new claims.
        self._prepare_claim_requests()
        self._schedule_outputs_if_any()

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return

        # Emit all prepared outputs at this simulation time.
        if self._prepared_claim_requests:
            self.output["claim_request_out"].extend(self._prepared_claim_requests)
        if self._prepared_assignments:
            self.output["assignment_out"].extend(self._prepared_assignments)

    def deltint(self):
        if self.phase != "OUTPUT_READY":
            self.passivate("WAITING")
            return

        # Clear emitted payloads
        self._prepared_claim_requests = []
        self._prepared_assignments = []

        # Optionally re-attempt claim initiation (zero-delay cycles) if still possible.
        self._prepare_claim_requests()
        self._schedule_outputs_if_any()

    def exit(self):
        pass