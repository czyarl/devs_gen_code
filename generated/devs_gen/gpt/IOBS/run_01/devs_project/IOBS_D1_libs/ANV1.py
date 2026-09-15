import json
import random
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ANV1(Atomic):
    """Atomic DEVS model: AccountNumberVerifier (ANV1).

    Receives validated login requests, applies a fixed processing delay per request,
    then performs a random 50/50 pass/fail decision at completion time.
    On completion, emits a required JSONL stdout record and forwards the original
    request unchanged only on pass.
    """

    def __init__(self, name: str, parent: Coupled | None, processing_delay_s: float):
        super().__init__(name)
        self.parent = parent
        self.processing_delay_s = float(processing_delay_s)

        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "to_pv_out"))

        # In-flight requests: list of (t_complete: float, payload: dict)
        self._pending: list[tuple[float, dict]] = []

    def initialize(self):
        self._pending = []
        self.passivate("IDLE")

    def _reschedule_from_pending(self) -> None:
        if not self._pending:
            self.passivate("IDLE")
            return
        now = get_current_time()
        next_time = min(t_complete for t_complete, _ in self._pending)
        self.hold_in("WAITING", max(0.0, next_time - now))

    def deltext(self, e: float):
        now = get_current_time()

        for msg in self.input["request_in"].values:
            try:
                payload = dict(msg)  # retain original request payload unchanged (copy)
                t_complete = now + self.processing_delay_s
                self._pending.append((t_complete, payload))
            except Exception as exc:
                print(f"ANV1: failed to accept payload {msg!r}: {exc}", file=sys.stderr, flush=True)

        self._reschedule_from_pending()

    def lambdaf(self):
        if self.phase != "WAITING":
            return

        now = get_current_time()

        # Emit one JSONL record per completion at this time; forward only on pass.
        for t_complete, payload in self._pending:
            if t_complete <= now:
                passed = 1 if random.random() < 0.5 else 0
                failed = 1 - passed

                print(
                    json.dumps(
                        {
                            "time": float(now),
                            "model": "ANV1",
                            "event": "verification",
                            "data": {"pass": int(passed), "fail": int(failed)},
                        }
                    ),
                    flush=True,
                )

                if passed == 1:
                    self.output["to_pv_out"].add(dict(payload))

    def deltint(self):
        now = get_current_time()
        self._pending = [(t_complete, payload) for t_complete, payload in self._pending if t_complete > now]
        self._reschedule_from_pending()

    def exit(self):
        pass