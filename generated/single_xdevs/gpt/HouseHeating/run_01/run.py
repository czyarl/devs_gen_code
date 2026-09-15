#!/usr/bin/env python3
import sys
import json
import math
import argparse
from dataclasses import dataclass
from typing import List, Tuple, Optional

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def parse_hhmmss_to_seconds(s: str) -> int:
    s = s.strip()
    parts = s.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid HH:MM:SS timestamp: {s!r}")
    hh, mm, ss = parts
    return int(hh) * 3600 + int(mm) * 60 + int(ss)


class OutdoorSchedule:
    """
    Stores (time_sec, temp_c) sorted by time_sec.
    Query returns the reading with greatest timestamp <= t, else default 25.0.
    """
    def __init__(self, readings: List[Tuple[int, float]], default_temp: float = 25.0):
        self.default_temp = float(default_temp)
        self.readings = sorted(readings, key=lambda x: x[0])
        self._times = [t for t, _ in self.readings]
        self._temps = [v for _, v in self.readings]

    def get(self, t: int) -> float:
        # binary search rightmost <= t
        lo, hi = 0, len(self._times)
        while lo < hi:
            mid = (lo + hi) // 2
            if self._times[mid] <= t:
                lo = mid + 1
            else:
                hi = mid
        idx = lo - 1
        if idx < 0:
            return self.default_temp
        return float(self._temps[idx])


@dataclass(frozen=True)
class TickMsg:
    time_sec: int


@dataclass(frozen=True)
class Observation:
    time_sec: int
    room_temp_c: float
    heat_loss_temp_c: float
    control_signal: int
    heater_output_c: float


class TickGenerator(Atomic):
    """
    Generates TickMsg at each integer simulation second: 1..N.
    """
    def __init__(self, name: str, parent: Optional[Coupled], simulate_time: float):
        super().__init__(name)
        self.parent = parent
        self.simulate_time = float(simulate_time)
        self.max_tick = int(self.simulate_time)

        self.add_out_port(Port(TickMsg, "tick"))

        self._next_tick = 1
        self._emit_tick: Optional[TickMsg] = None

        self.hold_in("INIT", 0.0)

    def initialize(self):
        self._next_tick = 1
        self._emit_tick = None
        # First tick at t=1.0
        if self.max_tick >= 1:
            self.hold_in("TICK", 1.0)
        else:
            self.hold_in("DONE", math.inf)

    def lambdaf(self):
        if self._emit_tick is not None:
            self.output["tick"].add(self._emit_tick)

    def deltint(self):
        if self.phase == "TICK":
            # Prepare payload for current tick time
            self._emit_tick = TickMsg(time_sec=self._next_tick)
            # After output, advance scheduling
            self._next_tick += 1
            if self._next_tick <= self.max_tick:
                self.hold_in("TICK", 1.0)
            else:
                self.hold_in("DONE", math.inf)
        else:
            self.hold_in(self.phase, math.inf)

    def deltext(self, e):
        # No external inputs
        self.hold_in(self.phase, self.sigma)

    def exit(self):
        pass


class HouseHeater(Atomic):
    """
    On each tick at time t (integer), computes the observation for that second
    using the previous second's room temp and control signal.
    """
    def __init__(self, name: str, parent: Optional[Coupled], schedule: OutdoorSchedule):
        super().__init__(name)
        self.parent = parent
        self.schedule = schedule

        self.add_in_port(Port(TickMsg, "tick"))
        self.add_out_port(Port(Observation, "obs"))

        # State at last completed observation time (t-1)
        self._room_temp_prev = 25.0          # room_temp at time 0
        self._control_prev = 0               # control_signal[0]
        self._last_time = 0

        # Prepared output
        self._emit_obs: Optional[Observation] = None

        self.hold_in("PASSIVE", math.inf)

    def initialize(self):
        self._room_temp_prev = 25.0
        self._control_prev = 0
        self._last_time = 0
        self._emit_obs = None
        self.hold_in("PASSIVE", math.inf)

    def _step(self, t: int) -> Observation:
        # Use outdoor temperature from previous second (t-1)
        outdoor_sched = self.schedule.get(t - 1)
        effective_outdoor = min(outdoor_sched, self._room_temp_prev)

        # Heat loss: lose 10% of gap to effective outdoor
        heat_loss_temp = self._room_temp_prev - 0.1 * (self._room_temp_prev - effective_outdoor)

        # Heater gain delayed by one step: based on previous control signal
        heater_output = 0.5 if self._control_prev == 1 else 0.0

        room_temp = heat_loss_temp + heater_output

        # Controller sets next control signal based on new room temp
        control_next = 1 if room_temp < 24.9 else 0

        # Update internal state to represent time t completed
        self._room_temp_prev = room_temp
        self._control_prev = control_next
        self._last_time = t

        return Observation(
            time_sec=t,
            room_temp_c=float(room_temp),
            heat_loss_temp_c=float(heat_loss_temp),
            control_signal=int(control_next),
            heater_output_c=float(heater_output),
        )

    def lambdaf(self):
        if self._emit_obs is not None:
            self.output["obs"].add(self._emit_obs)

    def deltint(self):
        # After emitting, go passive
        self._emit_obs = None
        self.hold_in("PASSIVE", math.inf)

    def deltext(self, e):
        # Process all ticks received at this time (should be at most one)
        ticks = list(self.input["tick"].values)
        # Clear prepared output; if multiple ticks, emit last (shouldn't happen)
        self._emit_obs = None

        for tick in ticks:
            t = int(tick.time_sec)
            # Ensure monotonic; if out-of-order, still compute based on current state
            self._emit_obs = self._step(t)

        # If we have an observation to emit, schedule immediate internal event
        if self._emit_obs is not None:
            self.hold_in("EMIT", 0.0)
        else:
            self.hold_in("PASSIVE", math.inf)

    def exit(self):
        pass


class JsonlSink(Atomic):
    """
    Prints Observation messages as JSONL to stdout.
    """
    def __init__(self, name: str, parent: Optional[Coupled]):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(Observation, "obs"))

        self._buffer: List[Observation] = []
        self.hold_in("PASSIVE", math.inf)

    def initialize(self):
        self._buffer = []
        self.hold_in("PASSIVE", math.inf)

    def lambdaf(self):
        # No output ports
        pass

    def deltint(self):
        # After printing, go passive
        self._buffer = []
        self.hold_in("PASSIVE", math.inf)

    def deltext(self, e):
        obs_list = list(self.input["obs"].values)
        if obs_list:
            self._buffer.extend(obs_list)
            # Print immediately at current sim time
            for obs in self._buffer:
                rec = {
                    "time_sec": int(obs.time_sec),
                    "room_temp_c": float(obs.room_temp_c),
                    "heat_loss_temp_c": float(obs.heat_loss_temp_c),
                    "control_signal": int(obs.control_signal),
                    "heater_output_c": float(obs.heater_output_c),
                }
                sys.stdout.write(json.dumps(rec, separators=(",", ":")) + "\n")
            sys.stdout.flush()
            self.hold_in("PRINTED", 0.0)
        else:
            self.hold_in("PASSIVE", math.inf)

    def exit(self):
        pass


class System(Coupled):
    def __init__(self, name: str, parent: Optional[Coupled], simulate_time: float, schedule: OutdoorSchedule):
        super().__init__(name)
        self.parent = parent

        tick = TickGenerator("tick_gen", parent=self, simulate_time=simulate_time)
        house = HouseHeater("house", parent=self, schedule=schedule)
        sink = JsonlSink("sink", parent=self)

        self.add_component(tick)
        self.add_component(house)
        self.add_component(sink)

        self.add_coupling(tick.output["tick"], house.input["tick"])
        self.add_coupling(house.output["obs"], sink.input["obs"])


def read_schedule_from_stdin() -> OutdoorSchedule:
    readings: List[Tuple[int, float]] = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            raise ValueError(f"Invalid schedule line: {line!r}")
        ts = parse_hhmmss_to_seconds(parts[0])
        temp = float(parts[1])
        readings.append((ts, temp))
    return OutdoorSchedule(readings, default_temp=25.0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate_time", type=float, required=True)
    args = parser.parse_args()

    schedule = read_schedule_from_stdin()

    root = System(name="system", parent=None, simulate_time=args.simulate_time, schedule=schedule)
    coord = Coordinator(root, clock=SimulationClock(0.0))
    coord.initialize()
    coord.simulate_time(float(args.simulate_time))


if __name__ == "__main__":
    main()