#!/usr/bin/env python3
import argparse
import json
import sys
import math
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


def parse_hhmmssmmm(s: str) -> float:
    """
    Parse HH:MM:SS:mmm into seconds (float).
    """
    parts = s.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid time format '{s}', expected HH:MM:SS:mmm")
    hh, mm, ss, mmm = parts
    h = int(hh)
    m = int(mm)
    sec = int(ss)
    ms = int(mmm)
    if not (0 <= m < 60 and 0 <= sec < 60 and 0 <= ms < 1000 and h >= 0):
        raise ValueError(f"Invalid time components in '{s}'")
    return h * 3600.0 + m * 60.0 + sec + ms / 1000.0


def format_hhmmssmmm(t: float) -> str:
    """
    Format seconds (float) into HH:MM:SS:mmm.
    Uses millisecond rounding to nearest ms.
    """
    if t < 0:
        t = 0.0
    total_ms = int(round(t * 1000.0))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{ms:03d}"


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def sample_truncated_normal(rng: random.Random, mean: float, stddev: float, lo: float, hi: float) -> float:
    """
    Sample from a normal distribution and clamp to [lo, hi].
    This satisfies the "sampled from or otherwise chosen within the allowed range" requirement.
    """
    if stddev == 0.0:
        return float(mean)
    v = rng.gauss(mean, stddev)
    return float(clamp(v, lo, hi))


@dataclass
class Event:
    time: float
    seq: int
    kind: str
    data: Dict[str, Any]


class EventLogger:
    def __init__(self, horizon: float):
        self.horizon = horizon

    def emit(self, time_val: float, event: str, entity_type: str, entity: str, payload: Dict[str, Any]) -> None:
        # Do not emit events after the horizon
        if time_val > self.horizon + 1e-12:
            return
        obj = {
            "time": float(time_val),
            "time_str": format_hhmmssmmm(time_val),
            "event": event,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload,
        }
        sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
        sys.stdout.flush()


class TwoEmployeeStoreSimulation:
    def __init__(
        self,
        horizon: float,
        client_mean: float,
        client_stddev: float,
        emp1_mean: float,
        emp1_stddev: float,
        emp2_mean: float,
        emp2_stddev: float,
        seed: Optional[int] = None,
    ):
        self.horizon = float(horizon)
        self.rng = random.Random(seed)

        self.client_mean = float(client_mean)
        self.client_stddev = float(client_stddev)

        self.emp_mean = {1: float(emp1_mean), 2: float(emp2_mean)}
        self.emp_std = {1: float(emp1_stddev), 2: float(emp2_stddev)}

        self.logger = EventLogger(self.horizon)

        # State
        self.now = 0.0
        self._seq = 0
        self._event_queue: List[Tuple[float, int, Event]] = []  # heap via manual insert (small scale)
        self.next_client_id = 1

        self.waiting_clients: List[int] = []  # FIFO client ids
        self.client_arrival_time: Dict[int, float] = {}
        self.client_paired_time: Dict[int, float] = {}
        self.client_paired_employee: Dict[int, int] = {}

        self.employee_busy: Dict[int, bool] = {1: False, 2: False}
        self.employee_current_client: Dict[int, Optional[int]] = {1: None, 2: None}

    def _push_event(self, time_val: float, kind: str, data: Dict[str, Any]) -> None:
        self._seq += 1
        ev = Event(time=float(time_val), seq=self._seq, kind=kind, data=data)
        # Insert into sorted list by (time, seq) to guarantee stable ordering
        key = (ev.time, ev.seq)
        idx = 0
        # Simple linear insert; event counts are modest for this scenario
        while idx < len(self._event_queue) and (self._event_queue[idx][0], self._event_queue[idx][1]) <= key:
            idx += 1
        self._event_queue.insert(idx, (ev.time, ev.seq, ev))

    def _pop_event(self) -> Optional[Event]:
        if not self._event_queue:
            return None
        _, _, ev = self._event_queue.pop(0)
        return ev

    def _schedule_next_arrival(self, current_time: float) -> None:
        """
        Schedule the next client generation after current_time.
        Inter-arrival interval must satisfy 0 <= interval <= mean + 5*stddev.
        """
        if self.client_stddev == 0.0:
            interval = self.client_mean
        else:
            lo = 0.0
            hi = self.client_mean + 5.0 * self.client_stddev
            interval = sample_truncated_normal(self.rng, self.client_mean, self.client_stddev, lo, hi)
        next_time = current_time + float(interval)
        # We can schedule beyond horizon; logger will suppress emission, but we also stop processing past horizon.
        self._push_event(next_time, "client_generated", {})

    def _sample_service_duration(self, employee_id: int) -> float:
        mean = self.emp_mean[employee_id]
        std = self.emp_std[employee_id]
        if std == 0.0:
            return float(mean)
        lo = mean - 3.0 * std
        hi = mean + 3.0 * std
        return sample_truncated_normal(self.rng, mean, std, lo, hi)

    def _emit_employee_available(self, t: float, employee_id: int) -> None:
        self.logger.emit(
            t,
            "employee_available",
            "employee",
            f"Employee_{employee_id}",
            {"employee_id": employee_id},
        )

    def _emit_client_generated(self, t: float, client_id: int) -> None:
        self.logger.emit(
            t,
            "client_generated",
            "client_generator",
            "ClientGenerator",
            {"client_id": client_id, "arrival_time": float(t)},
        )

    def _emit_client_paired(self, t: float, client_id: int, employee_id: int) -> None:
        self.logger.emit(
            t,
            "client_paired",
            "queue",
            "Queue",
            {"client_id": client_id, "employee_id": employee_id, "paired_time": float(t)},
        )

    def _emit_client_served(self, t: float, client_id: int, employee_id: int) -> None:
        arrived = self.client_arrival_time[client_id]
        dispatched = float(t)
        delay = dispatched - arrived
        self.logger.emit(
            t,
            "client_served",
            "employee",
            f"Employee_{employee_id}",
            {
                "client_id": client_id,
                "employee_id": employee_id,
                "arrived": float(arrived),
                "dispatched": float(dispatched),
                "delay": float(delay),
            },
        )

    def _try_pairing(self, t: float) -> None:
        """
        Pair as many waiting clients as possible with available employees.
        FIFO order for clients is enforced.
        Employee selection: lowest id available first (deterministic).
        """
        while self.waiting_clients:
            available = [eid for eid in (1, 2) if not self.employee_busy[eid]]
            if not available:
                return
            employee_id = min(available)
            client_id = self.waiting_clients.pop(0)

            # Pair immediately at time t
            self.employee_busy[employee_id] = True
            self.employee_current_client[employee_id] = client_id
            self.client_paired_time[client_id] = float(t)
            self.client_paired_employee[client_id] = employee_id

            self._emit_client_paired(t, client_id, employee_id)

            # Schedule service completion
            dur = self._sample_service_duration(employee_id)
            done_time = float(t) + float(dur)
            self._push_event(done_time, "client_served", {"employee_id": employee_id})

    def run(self) -> None:
        # Initial employee availability at t=0.0
        self._emit_employee_available(0.0, 1)
        self._emit_employee_available(0.0, 2)

        # First client at t=0.0
        self._push_event(0.0, "client_generated", {})

        # Main event loop
        while True:
            ev = self._pop_event()
            if ev is None:
                break
            if ev.time > self.horizon + 1e-12:
                break
            self.now = float(ev.time)

            if ev.kind == "client_generated":
                client_id = self.next_client_id
                self.next_client_id += 1

                self.client_arrival_time[client_id] = float(self.now)
                self.waiting_clients.append(client_id)
                self._emit_client_generated(self.now, client_id)

                # Schedule next arrival
                self._schedule_next_arrival(self.now)

                # Attempt pairing
                self._try_pairing(self.now)

            elif ev.kind == "client_served":
                employee_id = int(ev.data["employee_id"])
                client_id = self.employee_current_client[employee_id]
                if client_id is None:
                    # Should not happen; ignore safely
                    continue

                # Emit served event at completion time
                self._emit_client_served(self.now, client_id, employee_id)

                # Mark employee available
                self.employee_busy[employee_id] = False
                self.employee_current_client[employee_id] = None
                self._emit_employee_available(self.now, employee_id)

                # Attempt pairing immediately after becoming available
                self._try_pairing(self.now)

            else:
                # Unknown event kind; ignore
                continue


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Two-Employee Store Cashier Simulation (deterministic time, JSONL events).")
    p.add_argument("--simulation_time", type=str, default="00:05:00:000", help="Horizon in HH:MM:SS:mmm")
    p.add_argument("--client_mean", type=float, default=10.0)
    p.add_argument("--client_stddev", type=float, default=5.0)
    p.add_argument("--employee_1_mean", type=float, default=20.0)
    p.add_argument("--employee_1_stddev", type=float, default=0.0)
    p.add_argument("--employee_2_mean", type=float, default=30.0)
    p.add_argument("--employee_2_stddev", type=float, default=4.0)
    p.add_argument("--seed", type=int, default=None)
    return p


def main() -> None:
    args = build_arg_parser().parse_args()
    horizon = parse_hhmmssmmm(args.simulation_time)

    # Basic validation
    if horizon < 0:
        raise SystemExit("simulation_time must be non-negative")
    if args.client_mean < 0 or args.client_stddev < 0:
        raise SystemExit("client_mean and client_stddev must be non-negative")
    for name in ("employee_1_mean", "employee_2_mean"):
        if getattr(args, name) < 0:
            raise SystemExit(f"{name} must be non-negative")
    for name in ("employee_1_stddev", "employee_2_stddev"):
        if getattr(args, name) < 0:
            raise SystemExit(f"{name} must be non-negative")

    sim = TwoEmployeeStoreSimulation(
        horizon=horizon,
        client_mean=args.client_mean,
        client_stddev=args.client_stddev,
        emp1_mean=args.employee_1_mean,
        emp1_stddev=args.employee_1_stddev,
        emp2_mean=args.employee_2_mean,
        emp2_stddev=args.employee_2_stddev,
        seed=args.seed,
    )
    sim.run()


if __name__ == "__main__":
    main()