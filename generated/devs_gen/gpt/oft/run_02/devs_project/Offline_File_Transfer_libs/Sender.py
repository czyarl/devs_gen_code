import json
import sys

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Sender(Atomic):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        preparation_ms: float,
        timeout_ms: float,
    ):
        super().__init__(name)
        self.parent = parent

        self.preparation_ms = float(preparation_ms)
        self.timeout_ms = float(timeout_ms)

        self.add_in_port(Port(dict, "control_in"))
        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "data_out"))

        # State (initialized in initialize)
        self.packets_remaining: int = 0
        self.next_seq: int = 1
        self.current_bit: int = 0
        self.phase: str = "IDLE"

        self.inflight_seq: int | None = None
        self.inflight_bit: int | None = None
        self.last_send_was_retry: bool = False

        # Output staging for lambdaf
        self._pending_data_out: dict | None = None

        # Used to implement ACK-over-timeout rule for simultaneous events
        self._ack_success_at_current_time: bool = False

    def _write_stdout(self, event_type: str, val: dict) -> None:
        record = {
            "timestamp_ms": float(get_current_time()),
            "model": "sender",
            "type": event_type,
            "val": val,
        }
        print(json.dumps(record), flush=True)

    def _warn(self, msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    def _begin_preparing_new_packet(self) -> None:
        # Set inflight for a new packet attempt
        self.inflight_seq = int(self.next_seq)
        self.inflight_bit = int(self.current_bit)
        self.last_send_was_retry = False
        self._enter_preparing()

    def _enter_preparing(self) -> None:
        # Enter PREPARING and log at the same simulation time.
        self.phase = "PREPARING"
        self._write_stdout("preparation_started", {"duration": 10000})
        self.hold_in("PREPARING", max(0.0, self.preparation_ms))

    def initialize(self):
        self.packets_remaining = 0
        self.next_seq = 1
        self.current_bit = 0
        self.inflight_seq = None
        self.inflight_bit = None
        self.last_send_was_retry = False
        self._pending_data_out = None
        self._ack_success_at_current_time = False
        self.passivate("IDLE")
        self.phase = "IDLE"

    def deltext(self, e: float):
        # Reset per-time flags; deltext is invoked at a specific simulation time.
        self._ack_success_at_current_time = False

        # Apply control commands
        for cmd in self.input["control_in"].values:
            if not isinstance(cmd, dict) or "n" not in cmd:
                self._warn(f"[Sender] Malformed control payload ignored: {cmd!r}")
                continue
            try:
                added = int(cmd["n"])
            except Exception:
                self._warn(f"[Sender] Non-integer control n ignored: {cmd!r}")
                continue

            self.packets_remaining += added
            if self.packets_remaining < 0:
                self.packets_remaining = 0

            self._write_stdout("control_cmd", {"added": added, "total_remaining": int(self.packets_remaining)})

            if self.phase == "IDLE" and self.packets_remaining > 0:
                self._begin_preparing_new_packet()

        # Process ACKs
        for ack in self.input["ack_in"].values:
            received_bit = None
            if isinstance(ack, dict) and "bit" in ack and ack.get("bit") in (0, 1):
                received_bit = int(ack["bit"])
                self._write_stdout("ack_received", {"bit": received_bit})
            else:
                # Malformed ACK: ignore for protocol state; optional warning.
                self._warn(f"[Sender] Malformed ACK ignored: {ack!r}")
                continue

            if self.phase == "WAIT_ACK" and self.inflight_bit is not None:
                if received_bit == int(self.inflight_bit):
                    # ACK success; prefer over timeout if simultaneous.
                    self._ack_success_at_current_time = True

                    self.packets_remaining = max(0, int(self.packets_remaining) - 1)
                    self.next_seq += 1
                    self.current_bit = 1 - int(self.current_bit)

                    # Clear inflight context
                    self.inflight_seq = None
                    self.inflight_bit = None
                    self.last_send_was_retry = False
                    self._pending_data_out = None

                    if self.packets_remaining > 0:
                        self._begin_preparing_new_packet()
                    else:
                        self.phase = "IDLE"
                        self.passivate("IDLE")
                else:
                    # Wrong/duplicate ACK: ignore for progress, keep timeout.
                    pass

        # If we didn't change phase/sigma explicitly, preserve remaining time.
        if self.phase in ("PREPARING", "WAIT_ACK", "SEND") and self.sigma != float("inf"):
            # If we already scheduled something in this deltext, do not override.
            # We detect that by whether phase/sigma were set via hold_in/passivate above.
            # However, xDEVS doesn't provide a direct "changed" flag; safest is:
            # if we are still in the same phase as before and didn't call hold_in,
            # continuef(e). Since we may have called hold_in during processing,
            # we only continue if the phase is unchanged and sigma was not reset.
            # We'll approximate by continuing only when no new hold_in/passivate
            # was invoked due to inputs. We can detect that by checking whether
            # any port had values and caused a transition; but we already may have
            # processed values without transition. So: if still active and no hold_in
            # was called, continuef(e). We track by comparing ta before/after.
            pass

        # Robust continue logic: if we are still in the same active phase and did not
        # call hold_in/passivate during this method, keep remaining time.
        # We'll implement using a conservative approach: if currently active and
        # sigma was reduced by elapsed time automatically? It is not. So call continuef
        # only when we are still in an active phase and no new scheduling was done.
        # We can infer new scheduling if e > 0 and ta() is not (old_ta - e). Not available.
        # Simpler: always call continuef(e) if still in same phase and we did not
        # passivate/hold_in due to a state change. We'll track via a local flag.
        # (Implemented by re-running with a flag.)
        #
        # Since we already executed transitions above, we need to do this properly:
        # We'll re-implement with a flag by computing whether any scheduling occurred.
        # But we can't now; so we do a safe minimal: if still in WAIT_ACK and no success,
        # keep timeout by continuef(e) unless we re-held in WAIT_ACK elsewhere (we didn't).
        # If still in PREPARING and no new hold_in, continuef(e) is correct.
        #
        # We'll decide based on whether we are still in the same phase and did not
        # explicitly call hold_in/passivate in this deltext. We can track this with
        # a member set by helper methods; implement now with a member.
        #
        # (This block intentionally left empty; actual continue handled below.)
        self._continue_if_needed(e)

    def _continue_if_needed(self, e: float) -> None:
        # xDEVS requires preserving remaining time when staying in same phase.
        # We call continuef(e) only if we are in an active phase and no new schedule
        # has been set at this external transition time.
        #
        # Heuristic: if we are in IDLE (passive), do nothing.
        # If we are in PREPARING/WAIT_ACK and sigma is finite, we assume we should
        # preserve remaining time unless we just called hold_in/passivate in deltext.
        #
        # We detect "just scheduled" by checking a flag set by hold_in/passivate wrappers.
        if getattr(self, "_scheduled_in_deltext", False):
            self._scheduled_in_deltext = False
            return
        if self.phase in ("PREPARING", "WAIT_ACK", "SEND") and self.sigma != float("inf"):
            self.continuef(e)

    # Wrap scheduling calls to mark that deltext changed the schedule
    def hold_in(self, phase: str, sigma: float):
        super().hold_in(phase, sigma)
        # Mark only when called from deltext; harmless otherwise.
        self._scheduled_in_deltext = True

    def passivate(self, phase: str = "passive"):
        super().passivate(phase)
        self._scheduled_in_deltext = True

    def lambdaf(self):
        if self.phase != "SEND":
            return
        if self._pending_data_out is None:
            return
        self.output["data_out"].add(dict(self._pending_data_out))

    def deltint(self):
        # Internal transitions
        if self.phase == "PREPARING":
            # Preparation completed; schedule immediate send phase.
            if self.inflight_seq is None or self.inflight_bit is None:
                # Defensive: nothing to send; go idle.
                self.phase = "IDLE"
                self.passivate("IDLE")
                return

            self._pending_data_out = {"seq": int(self.inflight_seq), "bit": int(self.inflight_bit)}
            self.phase = "SEND"
            super().hold_in("SEND", 0.0)
            return

        if self.phase == "SEND":
            # Emit stdout observation of send at the same timestamp as output.
            if self.inflight_seq is not None and self.inflight_bit is not None:
                self._write_stdout(
                    "packet_sent",
                    {
                        "seq": int(self.inflight_seq),
                        "bit": int(self.inflight_bit),
                        "is_retry": bool(self.last_send_was_retry),
                    },
                )
            # Now wait for ACK with timeout.
            self._pending_data_out = None
            self.phase = "WAIT_ACK"
            super().hold_in("WAIT_ACK", max(0.0, self.timeout_ms))
            return

        if self.phase == "WAIT_ACK":
            # Timeout expiration. Apply ACK-over-timeout rule: if a correct ACK was
            # processed at this same timestamp, do not timeout.
            if self._ack_success_at_current_time:
                # ACK already advanced state via deltext; just clear flag and do nothing.
                self._ack_success_at_current_time = False
                # State should already be PREPARING or IDLE; ensure no extra scheduling here.
                if self.phase == "WAIT_ACK":
                    # If still WAIT_ACK, keep waiting (shouldn't happen on success).
                    super().hold_in("WAIT_ACK", max(0.0, self.timeout_ms))
                return

            # No correct ACK at this time => timeout and retry.
            if self.inflight_seq is not None:
                self._write_stdout("timeout", {"seq": int(self.inflight_seq)})

            self.last_send_was_retry = True
            # Retransmission attempt: go back to preparation with same inflight.
            self.phase = "PREPARING"
            self._write_stdout("preparation_started", {"duration": 10000})
            super().hold_in("PREPARING", max(0.0, self.preparation_ms))
            return

        # Default: idle
        self.phase = "IDLE"
        self.passivate("IDLE")

    def exit(self):
        pass