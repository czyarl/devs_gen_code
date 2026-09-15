import json
import sys
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class AAM1(Atomic):
    """
    Atomic DEVS model: AccountAccessManager (AAM1)

    - Single-server FIFO with fixed per-request processing delay.
    - On completion, writes exactly one JSONL record to stdout:
        * invalid == 0 -> account_generated
        * invalid != 0 -> logout
      and forwards the original request downstream only when invalid == 0.
    """

    def __init__(self, name: str, parent: Coupled | None, processing_delay_s: float):
        super().__init__(name)
        self.parent = parent
        self.processing_delay_s = float(processing_delay_s)

        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "to_anv"))

        self._queue: deque[dict] = deque()
        self._in_flight: dict | None = None

    def initialize(self):
        self._queue = deque()
        self._in_flight = None
        self.passivate("IDLE")

    def _start_next(self) -> None:
        self._in_flight = self._queue.popleft()
        delay = self.processing_delay_s
        if delay < 0.0:
            print(
                f"[AAM1] Diagnostic: processing_delay_s < 0 ({delay}); clamping to 0.0",
                file=sys.stderr,
                flush=True,
            )
            delay = 0.0
        self.hold_in("PROCESSING", float(delay))

    def deltext(self, e: float):
        was_processing = self.phase == "PROCESSING"
        remaining = max(0.0, self.ta() - e) if was_processing else None

        for req in self.input["request_in"].values:
            if not isinstance(req, dict):
                print(
                    f"[AAM1] Diagnostic: non-dict payload received on request_in: {type(req)}",
                    file=sys.stderr,
                    flush=True,
                )
                continue
            self._queue.append(req)

        if not was_processing and self._in_flight is None and self._queue:
            self._start_next()
        elif was_processing:
            self.hold_in("PROCESSING", remaining)

    def lambdaf(self):
        if self.phase != "PROCESSING" or self._in_flight is None:
            return

        now = float(get_current_time())
        req = self._in_flight

        invalid_raw = req.get("invalid", 0)
        try:
            invalid = int(invalid_raw)
        except Exception:
            print(
                f"[AAM1] Diagnostic: invalid field not int-castable ({invalid_raw!r}); treating as invalid",
                file=sys.stderr,
                flush=True,
            )
            invalid = 1

        if invalid != 0 and invalid != 1:
            print(
                f"[AAM1] Diagnostic: unexpected invalid value ({invalid}); treating as invalid",
                file=sys.stderr,
                flush=True,
            )
            invalid = 1

        if invalid == 0:
            record = {"time": now, "model": "AAM1", "event": "account_generated", "data": {}}
            print(json.dumps(record), flush=True)
            self.output["to_anv"].add(req)
        else:
            record = {"time": now, "model": "AAM1", "event": "logout", "data": {}}
            print(json.dumps(record), flush=True)

    def deltint(self):
        self._in_flight = None
        if self._queue:
            self._start_next()
        else:
            self.passivate("IDLE")

    def exit(self):
        pass