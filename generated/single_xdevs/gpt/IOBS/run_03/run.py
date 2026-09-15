#!/usr/bin/env python3
import argparse
import sys
import json
import logging
import random
import time
from collections import deque

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

INFINITY = float("inf")
SERVICE_TIME = 10.0


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )


def parse_timestamp_hhmmssmmm(ts: str) -> float:
    # Format: HH:MM:SS:mmm
    parts = ts.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Bad timestamp format: {ts!r}")
    hh = int(parts[0])
    mm = int(parts[1])
    ss = int(parts[2])
    mmm = int(parts[3])
    if not (0 <= mm < 60 and 0 <= ss < 60 and 0 <= mmm < 1000 and hh >= 0):
        raise ValueError(f"Timestamp out of range: {ts!r}")
    return hh * 3600.0 + mm * 60.0 + ss + (mmm / 1000.0)


def make_log(time_value: float, model: str, event: str, data: dict) -> dict:
    return {"time": float(time_value), "model": str(model), "event": str(event), "data": data}


class JsonlLogger(Atomic):
    """Receives log dicts and prints JSONL to stdout."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "in_log"))
        self.now = 0.0
        self.hold_in("PASSIVE", INFINITY)

    def initialize(self):
        self.now = 0.0
        self.hold_in("PASSIVE", INFINITY)

    def lambdaf(self):
        # No internal outputs
        return

    def deltint(self):
        # No internal events
        self.now += self.sigma
        self.hold_in("PASSIVE", INFINITY)

    def deltext(self, e):
        self.now += e
        for msg in list(self.input["in_log"].values):
            # Must print ONLY JSON objects to stdout.
            print(json.dumps(msg, separators=(",", ":")), file=sys.stdout, flush=True)
        self.hold_in("PASSIVE", INFINITY)

    def exit(self):
        return


class InputReader1(Atomic):
    """Reads all stdin lines at construction time, then emits requests at their timestamps."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "out_req"))
        self.add_out_port(Port(dict, "out_log"))

        self.events: list[tuple[float, int, int]] = []
        self.idx = 0
        self.now = 0.0
        self.req_id_next = 1

        self._load_stdin_events()
        self.hold_in("START", 0.0)

    def _load_stdin_events(self) -> None:
        events = []
        for line_no, raw in enumerate(sys.stdin, start=1):
            s = raw.strip()
            if not s:
                continue
            if "#" in s:
                s = s.split("#", 1)[0].strip()
                if not s:
                    continue
            parts = s.split()
            if len(parts) != 3:
                logging.warning("Skipping bad input line %d: %r", line_no, raw.rstrip("\n"))
                continue
            try:
                t = parse_timestamp_hhmmssmmm(parts[0])
                valid = int(parts[1])
                invalid = int(parts[2])
                events.append((t, valid, invalid))
            except Exception as ex:
                logging.warning("Skipping bad input line %d: %r (%s)", line_no, raw.rstrip("\n"), ex)
                continue
        events.sort(key=lambda x: x[0])
        self.events = events

    def initialize(self):
        self.idx = 0
        self.now = 0.0
        self.req_id_next = 1
        self.hold_in("START", 0.0)

    def lambdaf(self):
        t_out = self.now + self.sigma

        if self.phase == "START":
            self.output["out_log"].add(make_log(t_out, "input_reader1", "start", {}))
            return

        if self.phase == "EMIT":
            # Emit all events scheduled at exactly this time
            while self.idx < len(self.events) and self.events[self.idx][0] == t_out:
                _, valid, invalid = self.events[self.idx]
                req_id = self.req_id_next
                self.req_id_next += 1

                self.output["out_log"].add(
                    make_log(t_out, "input_reader1", "input", {"valid": int(valid), "invalid": int(invalid)})
                )
                self.output["out_req"].add({"req_id": req_id, "valid": int(valid), "invalid": int(invalid)})
                self.idx += 1

    def deltint(self):
        self.now += self.sigma

        if self.phase == "START":
            # Schedule first EMIT if any inputs exist
            if self.idx < len(self.events):
                dt = self.events[self.idx][0] - self.now
                self.hold_in("EMIT", max(0.0, dt))
            else:
                self.hold_in("PASSIVE", INFINITY)
            return

        if self.phase == "EMIT":
            if self.idx < len(self.events):
                dt = self.events[self.idx][0] - self.now
                self.hold_in("EMIT", max(0.0, dt))
            else:
                self.hold_in("PASSIVE", INFINITY)
            return

        self.hold_in("PASSIVE", INFINITY)

    def deltext(self, e):
        # No inputs expected
        self.now += e
        # Keep current scheduling
        if self.phase == "PASSIVE":
            self.hold_in("PASSIVE", INFINITY)
        else:
            self.hold_in(self.phase, max(0.0, self.sigma - e))

    def exit(self):
        return


class SingleServerAtomic(Atomic):
    """A single-server queue with fixed service time; emits prepared outputs at service completion."""

    def __init__(self, name: str, parent: Coupled | None, service_time: float = SERVICE_TIME):
        super().__init__(name)
        self.parent = parent
        self.service_time = float(service_time)

        self.now = 0.0
        self.queue = deque()
        self.current_job = None

        # Prepared outputs for lambdaf (purity: lambdaf only outputs)
        self._pending_logs: list[dict] = []
        self._pending_forwards: list[tuple[str, dict]] = []

        self.hold_in("PASSIVE", INFINITY)

    def initialize(self):
        self.now = 0.0
        self.queue.clear()
        self.current_job = None
        self._pending_logs = []
        self._pending_forwards = []
        self.hold_in("PASSIVE", INFINITY)

    def _start_service(self, job: dict) -> None:
        self.current_job = job
        logs, forwards = self._prepare_completion(job)
        self._pending_logs = list(logs)
        self._pending_forwards = list(forwards)
        self.hold_in("BUSY", self.service_time)

    def _prepare_completion(self, job: dict) -> tuple[list[dict], list[tuple[str, dict]]]:
        raise NotImplementedError

    def _on_service_complete(self, job: dict) -> None:
        # Optional hook for state commit at completion time (in deltint)
        return

    def lambdaf(self):
        if self.phase != "BUSY":
            return

        t_out = self.now + self.sigma
        # Ensure any logs missing time are time-stamped at completion (defensive)
        for msg in self._pending_logs:
            if "time" not in msg:
                msg["time"] = float(t_out)
            self.output["out_log"].add(msg)

        for port_name, payload in self._pending_forwards:
            self.output[port_name].add(payload)

    def deltint(self):
        self.now += self.sigma

        if self.phase == "BUSY":
            if self.current_job is not None:
                self._on_service_complete(self.current_job)

            self.current_job = None
            self._pending_logs = []
            self._pending_forwards = []

            if self.queue:
                self._start_service(self.queue.popleft())
            else:
                self.hold_in("PASSIVE", INFINITY)
            return

        self.hold_in("PASSIVE", INFINITY)

    def deltext(self, e):
        # Default: single input port "in_req"
        self.now += e

        arrivals = list(self.input["in_req"].values) if "in_req" in self.input else []
        for a in arrivals:
            self.queue.append(a)

        if self.phase == "PASSIVE":
            if self.queue:
                self._start_service(self.queue.popleft())
            else:
                self.hold_in("PASSIVE", INFINITY)
        else:
            rem = max(0.0, self.sigma - e)
            self.hold_in("BUSY", rem)

    def exit(self):
        return


class AAM1(SingleServerAtomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name, parent, service_time=SERVICE_TIME)
        self.add_in_port(Port(dict, "in_req"))
        self.add_out_port(Port(dict, "out_to_anv"))
        self.add_out_port(Port(dict, "out_log"))

    def _prepare_completion(self, job: dict):
        t_out = self.now + self.service_time
        invalid = int(job.get("invalid", 0))
        req_id = int(job["req_id"])

        if invalid == 1:
            logs = [make_log(t_out, "AAM1", "logout", {})]
            forwards = []
        else:
            logs = [make_log(t_out, "AAM1", "account_generated", {})]
            forwards = [("out_to_anv", {"req_id": req_id})]
        return logs, forwards


class ANV1(SingleServerAtomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name, parent, service_time=SERVICE_TIME)
        self.add_in_port(Port(dict, "in_req"))
        self.add_out_port(Port(dict, "out_to_pv"))
        self.add_out_port(Port(dict, "out_log"))

    def _prepare_completion(self, job: dict):
        t_out = self.now + self.service_time
        req_id = int(job["req_id"])

        passed = 1 if (random.random() < 0.5) else 0
        failed = 1 - passed

        logs = [make_log(t_out, "ANV1", "verification", {"pass": passed, "fail": failed})]
        forwards = [("out_to_pv", {"req_id": req_id})] if passed else []
        return logs, forwards


class PV1(SingleServerAtomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name, parent, service_time=SERVICE_TIME)
        self.add_in_port(Port(dict, "in_req"))
        self.add_out_port(Port(dict, "out_to_bpm"))
        self.add_out_port(Port(dict, "out_log"))

    def _prepare_completion(self, job: dict):
        t_out = self.now + self.service_time
        req_id = int(job["req_id"])

        # Geometric trials with p=0.5, at least 1 attempt; always success eventually.
        attempts = 1
        while random.random() >= 0.5:
            attempts += 1

        logs = [make_log(t_out, "PV1", "verification", {"success": 1, "attempts": int(attempts)})]
        forwards = [("out_to_bpm", {"req_id": req_id})]
        return logs, forwards


class BPM1(SingleServerAtomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name, parent, service_time=SERVICE_TIME)
        self.add_in_port(Port(dict, "in_req"))
        self.add_in_port(Port(dict, "in_balance"))
        self.add_out_port(Port(dict, "out_to_tpm"))
        self.add_out_port(Port(dict, "out_log"))

        self.confirmed_balance = 3000
        self.reserved_by_id: dict[int, int] = {}

    def initialize(self):
        super().initialize()
        self.confirmed_balance = 3000
        self.reserved_by_id = {}

    def _available_balance(self) -> int:
        reserved = sum(int(v) for v in self.reserved_by_id.values())
        return max(0, int(self.confirmed_balance) - reserved)

    def deltext(self, e):
        self.now += e

        # Balance updates can arrive while BUSY or PASSIVE
        for msg in list(self.input["in_balance"].values):
            try:
                req_id = int(msg.get("req_id", -1))
                remaining = int(msg.get("remaining", self.confirmed_balance))
                self.confirmed_balance = remaining
                if req_id in self.reserved_by_id:
                    self.reserved_by_id.pop(req_id, None)
            except Exception:
                # Ignore malformed balance update
                continue

        arrivals = list(self.input["in_req"].values)
        for a in arrivals:
            self.queue.append(a)

        if self.phase == "PASSIVE":
            if self.queue:
                self._start_service(self.queue.popleft())
            else:
                self.hold_in("PASSIVE", INFINITY)
        else:
            rem = max(0.0, self.sigma - e)
            self.hold_in("BUSY", rem)

    def _prepare_completion(self, job: dict):
        t_out = self.now + self.service_time
        req_id = int(job["req_id"])

        cap = min(40, self._available_balance())
        if cap < 0:
            cap = 0
        amount = int(random.randint(0, cap))

        # Reserve this amount until TPM confirms via feedback
        self.reserved_by_id[req_id] = amount

        logs = [make_log(t_out, "BPM1", "bill", {"amount": amount})]
        forwards = [("out_to_tpm", {"req_id": req_id, "amount": amount})]
        return logs, forwards


class TPM1(SingleServerAtomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name, parent, service_time=SERVICE_TIME)
        self.add_in_port(Port(dict, "in_req"))
        self.add_out_port(Port(dict, "out_balance"))
        self.add_out_port(Port(dict, "out_log"))

        self.balance = 3000
        self.count = 0
        self._pending_new_balance = None
        self._pending_req_id = None

    def initialize(self):
        super().initialize()
        self.balance = 3000
        self.count = 0
        self._pending_new_balance = None
        self._pending_req_id = None

    def _prepare_completion(self, job: dict):
        t_out = self.now + self.service_time
        req_id = int(job["req_id"])
        amount = int(job.get("amount", 0))
        if amount < 0:
            amount = 0
        if amount > self.balance:
            amount = self.balance

        new_balance = int(self.balance - amount)
        new_count = int(self.count + 1)

        # Commit at completion time (deltint) but compute now for lambdaf outputs
        self._pending_new_balance = new_balance
        self._pending_req_id = req_id

        logs = [make_log(t_out, "TPM1", "transaction", {"remaining": new_balance, "count": new_count})]
        forwards = [("out_balance", {"req_id": req_id, "remaining": new_balance})]
        return logs, forwards

    def _on_service_complete(self, job: dict) -> None:
        # Commit the balance and transaction count at completion time
        if self._pending_new_balance is not None:
            self.balance = int(self._pending_new_balance)
            self.count = int(self.count + 1)
        self._pending_new_balance = None
        self._pending_req_id = None


class IOBSSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        logger = JsonlLogger("logger", parent=self)
        input_reader1 = InputReader1("input_reader1", parent=self)
        aam1 = AAM1("AAM1", parent=self)
        anv1 = ANV1("ANV1", parent=self)
        pv1 = PV1("PV1", parent=self)
        bpm1 = BPM1("BPM1", parent=self)
        tpm1 = TPM1("TPM1", parent=self)

        for c in (logger, input_reader1, aam1, anv1, pv1, bpm1, tpm1):
            self.add_component(c)

        # Main pipeline
        self.add_coupling(input_reader1.output["out_req"], aam1.input["in_req"])
        self.add_coupling(aam1.output["out_to_anv"], anv1.input["in_req"])
        self.add_coupling(anv1.output["out_to_pv"], pv1.input["in_req"])
        self.add_coupling(pv1.output["out_to_bpm"], bpm1.input["in_req"])
        self.add_coupling(bpm1.output["out_to_tpm"], tpm1.input["in_req"])

        # Feedback balance
        self.add_coupling(tpm1.output["out_balance"], bpm1.input["in_balance"])

        # Logs to logger
        self.add_coupling(input_reader1.output["out_log"], logger.input["in_log"])
        self.add_coupling(aam1.output["out_log"], logger.input["in_log"])
        self.add_coupling(anv1.output["out_log"], logger.input["in_log"])
        self.add_coupling(pv1.output["out_log"], logger.input["in_log"])
        self.add_coupling(bpm1.output["out_log"], logger.input["in_log"])
        self.add_coupling(tpm1.output["out_log"], logger.input["in_log"])


def main() -> int:
    _setup_logging()

    parser = argparse.ArgumentParser(prog="run.py")
    parser.add_argument("--simulation_time", type=float, default=1000000.0)
    args = parser.parse_args()

    # Seed randomness from system time
    seed = time.time_ns()
    random.seed(seed)
    logging.info("Random seed: %s", seed)

    root = IOBSSystem(name="system", parent=None)
    coord = Coordinator(root, clock=SimulationClock(0.0))
    coord.initialize()
    coord.simulate_time(float(args.simulation_time))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())