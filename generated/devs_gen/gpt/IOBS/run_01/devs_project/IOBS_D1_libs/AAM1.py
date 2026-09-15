import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class AAM1(Atomic):
    """
    AccountAccessManager (AAM1)

    Receives timestamped login requests and, for each request, schedules a fixed
    processing delay. At completion time, emits exactly one stdout JSONL record
    and conditionally forwards the request to ANV1.
    """

    def __init__(self, name: str, parent: Coupled | None, processing_delay_s: float):
        super().__init__(name)
        self.parent = parent
        self.processing_delay_s = float(processing_delay_s)

        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "to_anv_out"))

        # List of (t_complete: float, seq: int, payload: dict)
        self._pending: list[tuple[float, int, dict]] = []
        self._seq: int = 0

    def initialize(self):
        self._pending = []
        self._seq = 0
        self.passivate("IDLE")

    def _reschedule_from_pending(self) -> None:
        if not self._pending:
            self.passivate("IDLE")
            return
        now = get_current_time()
        next_t = min(t_complete for t_complete, _, _ in self._pending)
        self.hold_in("WAITING", max(0.0, next_t - now))

    @staticmethod
    def _stdout_event(time_value: float, model_name: str, event_name: str) -> None:
        print(json.dumps({
            "time": float(time_value),
            "model": model_name,
            "event": event_name,
            "data": {},
        }), flush=True)

    def deltext(self, e: float):
        now = get_current_time()

        for msg in self.input["request_in"].values:
            # Keep payload unchanged for forwarding; store a copy to avoid aliasing.
            try:
                payload = dict(msg)
            except Exception:
                payload = msg  # if it's already a dict-like, keep as-is

            t_complete = now + self.processing_delay_s
            self._pending.append((t_complete, self._seq, payload))
            self._seq += 1

        self._reschedule_from_pending()

    def lambdaf(self):
        if self.phase != "WAITING":
            return

        now = get_current_time()

        # Emit all completions due at 'now' (or earlier, due to numerical effects),
        # in deterministic order: by completion time then insertion sequence.
        due = [(t, s, p) for (t, s, p) in self._pending if t <= now]
        if not due:
            return

        due.sort(key=lambda x: (x[0], x[1]))

        for t_complete, _, payload in due:
            invalid_val = payload.get("invalid", 1)
            if invalid_val not in (0, 1):
                print(
                    f"AAM1 warning: invalid value {invalid_val!r} treated as 1 (logout).",
                    file=sys.stderr,
                    flush=True,
                )
                invalid_val = 1

            if invalid_val == 0:
                self._stdout_event(t_complete, self.name, "account_generated")
                self.output["to_anv_out"].add(dict(payload))
            else:
                self._stdout_event(t_complete, self.name, "logout")

    def deltint(self):
        now = get_current_time()
        self._pending = [(t, s, p) for (t, s, p) in self._pending if t > now]
        self._reschedule_from_pending()

    def exit(self):
        pass