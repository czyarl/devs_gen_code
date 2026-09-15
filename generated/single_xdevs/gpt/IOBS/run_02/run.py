#!/usr/bin/env python3
import argparse
import sys
import json
import logging
import random
import time
from collections import deque

# Allowed imports (some unused but permitted by requirements)
import simpy  # noqa: F401

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

INF = float("inf")


def parse_hhmmss_mmm(ts: str) -> float:
    """
    Parse timestamp in HH:MM:SS:mmm into seconds (float).
    """
    parts = ts.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid timestamp format: {ts!r}")
    hh, mm, ss, mmm = (int(p) for p in parts)
    return hh * 3600.0 + mm * 60.0 + ss + (mmm / 1000.0)


def emit_json_event(sim_time: float, model: str, event: str, data: dict) -> None:
    obj = {"time": float(sim_time), "model": str(model), "event": str(event), "data": dict(data)}
    print(json.dumps(obj, separators=(",", ":")), file=sys.stdout, flush=True)


class InputReader1(Atomic):
    """
    Emits requests at their input timestamps.
    Also emits a 'start' event at t=0.0.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_out_port(Port(dict, "out"))

        self._events: list[tuple[float, int, int, int]] = []  # (time, valid, invalid, rid)
        self._idx = 0
        self._pending_payload: dict | None = None
        self._pending_log: tuple[str, dict] | None = None

        self.hold_in("BOOT", 0.0)

    def initialize(self):
        # Read stdin fully (line-by-line) during initialization.
        rid = 0
        events = []
        for line in sys.stdin:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Allow inline comments after data
            if "#" in line:
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
            parts = line.split()
            if len(parts) < 3:
                logging.warning("Skipping invalid input line: %r", line)
                continue
            ts_s, valid_s, invalid_s = parts[0], parts[1], parts[2]
            try:
                t = parse_hhmmss_mmm(ts_s)
                valid = int(valid_s)
                invalid = int(invalid_s)
            except Exception as ex:
                logging.warning("Skipping unparsable line %r: %s", line, ex)
                continue
            events.append((t, valid, invalid, rid))
            rid += 1

        # Stable-sort by time; preserve original order for equal times via rid.
        events.sort(key=lambda x: (x[0], x[3]))
        self._events = events
        self._idx = 0

        # Emit start at t=0
        self._pending_log = ("start", {})
        self._pending_payload = None
        self.hold_in("START", 0.0)

    def lambdaf(self):
        t = getattr(self, "t_next", 0.0)
        if self._pending_log is not None:
            ev, data = self._pending_log
            emit_json_event(t, self.name, ev, data)

        if self._pending_payload is not None:
            self.output["out"].add(self._pending_payload)

    def deltint(self):
        # After START, schedule first input emit (if any). After EMIT, schedule next.
        now = getattr(self, "t_next", 0.0)
        self._pending_log = None
        self._pending_payload = None

        if self.phase == "START":
            if self._idx >= len(self._events):
                self.hold_in("IDLE", INF)
                return
            t, valid, invalid, rid = self._events[self._idx]
            sigma = max(0.0, t - now)
            self._pending_log = ("input", {"valid": int(valid), "invalid": int(invalid)})
            self._pending_payload = {"rid": rid, "valid": int(valid), "invalid": int(invalid)}
            self.hold_in("EMIT", sigma)
            return

        if self.phase == "EMIT":
            self._idx += 1
            if self._idx >= len(self._events):
                self.hold_in("IDLE", INF)
                return
            t, valid, invalid, rid = self._events[self._idx]
            sigma = max(0.0, t - now)
            self._pending_log = ("input", {"valid": int(valid), "invalid": int(invalid)})
            self._pending_payload = {"rid": rid, "valid": int(valid), "invalid": int(invalid)}
            self.hold_in("EMIT", sigma)
            return

        self.hold_in("IDLE", INF)

    def deltext(self, e):
        # No external inputs.
        # Keep current scheduling.
        if self.phase in ("START", "EMIT"):
            # Maintain remaining time
            remain = max(0.0, self.sigma - float(e))
            self.hold_in(self.phase, remain)
        else:
            self.hold_in("IDLE", INF)

    def exit(self):
        pass


class SingleServerStage(Atomic):
    """
    Generic single-server FIFO stage:
    - Processes each incoming message with a fixed delay (service_time).
    - Pre-computes the output/log at service start and emits on completion.
    """

    def __init__(self, name: str, parent: Coupled | None, service_time: float = 10.0):
        super().__init__(name)
        self.parent = parent
        self.service_time = float(service_time)

        self.add_in_port(Port(dict, "in"))
        self.add_out_port(Port(dict, "out"))

        self._q = deque()
        self._current = None

        self._pending_log: tuple[str, dict] | None = None
        self._pending_out: dict | None = None

        self.hold_in("IDLE", INF)

    def initialize(self):
        self._q.clear()
        self._current = None
        self._pending_log = None
        self._pending_out = None
        self.hold_in("IDLE", INF)

    def _start_service(self, msg: dict):
        """
        Must set:
        - self._pending_log = (event_name, data_dict)
        - self._pending_out = payload dict or None
        Then schedule BUSY for service_time.
        """
        raise NotImplementedError

    def _on_service_complete(self):
        """
        Optional hook called in deltint after lambdaf for the completed job.
        (State updates belong here.)
        """
        pass

    def lambdaf(self):
        t = getattr(self, "t_next", 0.0)
        if self._pending_log is not None:
            ev, data = self._pending_log
            emit_json_event(t, self.name, ev, data)
        if self._pending_out is not None:
            self.output["out"].add(self._pending_out)

    def deltint(self):
        # Completion of current job
        self._on_service_complete()

        self._current = None
        self._pending_log = None
        self._pending_out = None

        if self._q:
            msg = self._q.popleft()
            self._current = msg
            self._start_service(msg)
            return

        self.hold_in("IDLE", INF)

    def deltext(self, e):
        # Enqueue all incoming messages
        for msg in list(self.input["in"].values):
            self._q.append(msg)

        if self.phase == "IDLE":
            if self._q:
                msg = self._q.popleft()
                self._current = msg
                self._start_service(msg)
            else:
                self.hold_in("IDLE", INF)
            return

        # BUSY: keep remaining time (do not reset service)
        remain = max(0.0, float(self.sigma) - float(e))
        self.hold_in("BUSY", remain)

    def exit(self):
        pass


class AAM1(SingleServerStage):
    def _start_service(self, msg: dict):
        invalid = int(msg.get("invalid", 0))
        rid = msg.get("rid")
        if invalid == 1:
            self._pending_log = ("logout", {})
            self._pending_out = None
        else:
            self._pending_log = ("account_generated", {})
            self._pending_out = {"rid": rid}
        self.hold_in("BUSY", self.service_time)


class ANV1(SingleServerStage):
    def _start_service(self, msg: dict):
        rid = msg.get("rid")
        passed = 1 if (random.random() < 0.5) else 0
        failed = 1 - passed
        self._pending_log = ("verification", {"pass": int(passed), "fail": int(failed)})
        self._pending_out = {"rid": rid} if passed else None
        self.hold_in("BUSY", self.service_time)


class PV1(SingleServerStage):
    def _start_service(self, msg: dict):
        rid = msg.get("rid")
        # Geometric(p=0.5) attempts until success
        attempts = 1
        while random.random() >= 0.5:
            attempts += 1
        self._pending_log = ("verification", {"success": 1, "attempts": int(attempts)})
        self._pending_out = {"rid": rid}
        self.hold_in("BUSY", self.service_time)


class BPM1(SingleServerStage):
    def __init__(self, name: str, parent: Coupled | None, service_time: float = 10.0, initial_balance: int = 3000):
        super().__init__(name, parent, service_time=service_time)
        self._reserved_balance = int(initial_balance)

    def initialize(self):
        super().initialize()
        self._reserved_balance = int(self._reserved_balance)

    def _start_service(self, msg: dict):
        rid = msg.get("rid")
        max_amt = min(40, max(0, int(self._reserved_balance)))
        amount = random.randint(0, max_amt) if max_amt > 0 else 0

        # Reserve immediately to prevent overspending under pipelining
        self._reserved_balance -= int(amount)

        self._pending_log = ("bill", {"amount": int(amount)})
        self._pending_out = {"rid": rid, "amount": int(amount)}
        self.hold_in("BUSY", self.service_time)


class TPM1(SingleServerStage):
    def __init__(self, name: str, parent: Coupled | None, service_time: float = 10.0, initial_balance: int = 3000):
        super().__init__(name, parent, service_time=service_time)
        self.balance = int(initial_balance)
        self.count = 0
        self._pending_remaining: int | None = None
        self._pending_count: int | None = None

    def initialize(self):
        super().initialize()
        self.balance = int(self.balance)
        self.count = int(self.count)
        self._pending_remaining = None
        self._pending_count = None

    def _start_service(self, msg: dict):
        amount = int(msg.get("amount", 0))
        remaining_after = int(self.balance) - int(amount)
        count_after = int(self.count) + 1

        self._pending_remaining = remaining_after
        self._pending_count = count_after

        self._pending_log = ("transaction", {"remaining": int(remaining_after), "count": int(count_after)})
        self._pending_out = None
        self.hold_in("BUSY", self.service_time)

    def _on_service_complete(self):
        # Apply the state updates after producing the output (lambdaf has already run).
        if self._pending_remaining is not None and self._pending_count is not None:
            self.balance = int(self._pending_remaining)
            self.count = int(self._pending_count)
        self._pending_remaining = None
        self._pending_count = None


class IOBS(Coupled):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.reader = InputReader1("input_reader1", parent=self)
        self.aam = AAM1("AAM1", parent=self, service_time=10.0)
        self.anv = ANV1("ANV1", parent=self, service_time=10.0)
        self.pv = PV1("PV1", parent=self, service_time=10.0)
        self.bpm = BPM1("BPM1", parent=self, service_time=10.0, initial_balance=3000)
        self.tpm = TPM1("TPM1", parent=self, service_time=10.0, initial_balance=3000)

        for c in (self.reader, self.aam, self.anv, self.pv, self.bpm, self.tpm):
            self.add_component(c)

        self.add_coupling(self.reader.output["out"], self.aam.input["in"])
        self.add_coupling(self.aam.output["out"], self.anv.input["in"])
        self.add_coupling(self.anv.output["out"], self.pv.input["in"])
        self.add_coupling(self.pv.output["out"], self.bpm.input["in"])
        self.add_coupling(self.bpm.output["out"], self.tpm.input["in"])


def main():
    parser = argparse.ArgumentParser(prog="run.py")
    parser.add_argument("--simulation_time", type=float, default=1000000.0)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    # Seed RNG using system time
    seed = time.time_ns()
    random.seed(seed)

    root = IOBS(name="system", parent=None)
    coord = Coordinator(root, clock=SimulationClock(0.0))
    coord.initialize()
    coord.simulate_time(float(args.simulation_time))


if __name__ == "__main__":
    main()