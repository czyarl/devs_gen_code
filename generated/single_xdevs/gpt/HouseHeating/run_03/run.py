#!/usr/bin/env python3
import argparse
import json
import sys
from dataclasses import dataclass
from typing import List, Tuple, Optional

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock


def _parse_hhmmss_to_seconds(s: str) -> int:
    parts = s.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid HH:MM:SS timestamp: {s!r}")
    h, m, sec = (int(parts[0]), int(parts[1]), int(parts[2]))
    if h < 0 or m < 0 or m >= 60 or sec < 0 or sec >= 60:
        raise ValueError(f"Invalid HH:MM:SS timestamp values: {s!r}")
    return h * 3600 + m * 60 + sec


def read_outdoor_schedule_from_stdin() -> List[Tuple[int, float]]:
    """
    Reads lines: 'HH:MM:SS temp'
    Returns sorted list of (time_sec, temp_c). If duplicates, last one wins.
    """
    entries: List[Tuple[int, float]] = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        # allow multiple spaces/tabs
        parts = line.split()
        if len(parts) < 2:
            print(f"Skipping invalid schedule line (needs 2 tokens): {line!r}", file=sys.stderr)
            continue
        try:
            t = _parse_hhmmss_to_seconds(parts[0])
            temp = float(parts[1])
            entries.append((t, temp))
        except Exception as e:
            print(f"Skipping invalid schedule line {line!r}: {e}", file=sys.stderr)

    # sort and collapse duplicates by keeping last for same timestamp
    entries.sort(key=lambda x: x[0])
    collapsed: List[Tuple[int, float]] = []
    for t, temp in entries:
        if collapsed and collapsed[-1][0] == t:
            collapsed[-1] = (t, temp)
        else:
            collapsed.append((t, temp)
            )
    return collapsed


@dataclass(frozen=True)
class Observation:
    time_sec: int
    room_temp_c: float
    heat_loss_temp_c: float
    control_signal: int
    heater_output_c: float


class OutdoorSchedule(Atomic):
    """
    Provides outdoor temperature for requested times.
    Input: req_time (int seconds)
    Output: outdoor_temp (float)
    """
    def __init__(self, name: str, parent: Optional[Coupled], schedule: List[Tuple[int, float]]):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(int, "req_time"))
        self.add_out_port(Port(float, "outdoor_temp"))

        self._schedule = schedule
        self._idx = 0  # points to next schedule entry time > current query time (maintained on lookup)
        self._last_temp = 25.0  # default if no reading <= t
        self._pending_out: Optional[float] = None

    def initialize(self):
        self._idx = 0
        self._last_temp = 25.0
        self._pending_out = None
        self.hold_in("PASSIVE", float("inf"))

    def _lookup(self, t: int) -> float:
        # Advance idx while schedule time <= t, updating last_temp
        while self._idx < len(self._schedule) and self._schedule[self._idx][0] <= t:
            self._last_temp = self._schedule[self._idx][1]
            self._idx += 1
        return self._last_temp

    def lambdaf(self):
        if self._pending_out is not None:
            self.output["outdoor_temp"].add(self._pending_out)

    def deltint(self):
        # After output, go passive
        self._pending_out = None
        self.hold_in("PASSIVE", float("inf"))

    def deltext(self, e):
        # On request(s), respond immediately with the last request's lookup.
        # Deterministic: if multiple requests arrive at same time, last one wins.
        reqs = list(self.input["req_time"].values)
        if reqs:
            t = int(reqs[-1])
            self._pending_out = float(self._lookup(t))
            self.hold_in("RESPOND", 0.0)
        else:
            self.hold_in("PASSIVE", float("inf"))

    def exit(self):
        pass


class HouseControllerPlant(Atomic):
    """
    Combined plant + controller with 1-second discrete updates.
    Requests outdoor temperature for previous second, then updates state and emits observation.

    Outputs:
      - req_time (int): request outdoor temp for (t-1)
      - observation (Observation): state at time t (for t>=1)
    Inputs:
      - outdoor_temp (float): response to request
    """
    def __init__(self, name: str, parent: Optional[Coupled]):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(float, "outdoor_temp"))
        self.add_out_port(Port(int, "req_time"))
        self.add_out_port(Port(Observation, "observation"))

        # State
        self._t = 0  # current integer time of last committed room_temp (t=0 initial)
        self._room_temp = 25.0
        self._control_signal = 0  # control_signal[0]=0
        self._pending_req_time: Optional[int] = None
        self._pending_obs: Optional[Observation] = None

        # For update step
        self._awaiting_outdoor_for_t_minus_1: Optional[int] = None
        self._received_outdoor: Optional[float] = None

    def initialize(self):
        self._t = 0
        self._room_temp = 25.0
        self._control_signal = 0
        self._pending_req_time = None
        self._pending_obs = None
        self._awaiting_outdoor_for_t_minus_1 = None
        self._received_outdoor = None

        # Immediately request outdoor for t=0 (previous second for first update to t=1)
        self._pending_req_time = 0
        self._awaiting_outdoor_for_t_minus_1 = 0
        self.hold_in("REQUEST", 0.0)

    def lambdaf(self):
        # Output request and/or observation prepared in transitions
        if self._pending_req_time is not None:
            self.output["req_time"].add(int(self._pending_req_time))
        if self._pending_obs is not None:
            self.output["observation"].add(self._pending_obs)

    def deltint(self):
        # Clear outputs and wait for response or schedule next request
        if self.phase == "REQUEST":
            # After sending request, wait for outdoor response
            self._pending_req_time = None
            self.hold_in("WAIT_OUTDOOR", float("inf"))
            return

        if self.phase == "EMIT_OBS":
            # After emitting observation, immediately request next outdoor for current time t (which is new "previous")
            self._pending_obs = None
            self._pending_req_time = self._t  # request outdoor for previous second of next step
            self._awaiting_outdoor_for_t_minus_1 = self._t
            self._received_outdoor = None
            self.hold_in("REQUEST", 0.0)
            return

        # Default: remain passive
        self.hold_in("WAIT_OUTDOOR", float("inf"))

    def deltext(self, e):
        # Receive outdoor temp; compute next step and prepare observation
        vals = list(self.input["outdoor_temp"].values)
        if not vals:
            # nothing to do
            self.hold_in(self.phase, self.sigma)
            return

        outdoor = float(vals[-1])
        self._received_outdoor = outdoor

        # We expect this corresponds to t-1 = self._awaiting_outdoor_for_t_minus_1
        # Update from time t to t+1 (but our _t is last committed time)
        # For first update, _t=0 and we asked for 0, so we compute time 1.
        prev_t = self._t
        next_t = prev_t + 1

        prev_room = self._room_temp
        prev_control = int(self._control_signal)

        # Effective outdoor for previous second: scheduled outdoor capped to prev_room
        eff_outdoor = outdoor if outdoor <= prev_room else prev_room

        # Heat loss: lose 10% of gap to effective outdoor
        heat_loss_temp = prev_room - 0.1 * (prev_room - eff_outdoor)

        # Heater gain delayed by one step: based on previous control
        heater_output = 0.5 if prev_control == 1 else 0.0

        new_room = heat_loss_temp + heater_output

        # Controller sets next control based on new room temp
        next_control = 1 if new_room < 24.9 else 0

        # Commit state
        self._t = next_t
        self._room_temp = new_room
        self._control_signal = next_control

        # Prepare observation for time next_t
        self._pending_obs = Observation(
            time_sec=next_t,
            room_temp_c=float(new_room),
            heat_loss_temp_c=float(heat_loss_temp),
            control_signal=int(next_control),
            heater_output_c=float(heater_output),
        )

        # Emit observation immediately
        self.hold_in("EMIT_OBS", 0.0)

    def exit(self):
        pass


class JsonlSink(Atomic):
    """
    Prints observations as JSONL to stdout.
    """
    def __init__(self, name: str, parent: Optional[Coupled], max_time: int):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(Observation, "observation"))
        self._max_time = int(max_time)
        self._pending: Optional[Observation] = None

    def initialize(self):
        self._pending = None
        self.hold_in("PASSIVE", float("inf"))

    def lambdaf(self):
        if self._pending is None:
            return
        obs = self._pending
        if 1 <= obs.time_sec <= self._max_time:
            rec = {
                "time_sec": int(obs.time_sec),
                "room_temp_c": float(obs.room_temp_c),
                "heat_loss_temp_c": float(obs.heat_loss_temp_c),
                "control_signal": int(obs.control_signal),
                "heater_output_c": float(obs.heater_output_c),
            }
            print(json.dumps(rec, separators=(",", ":")), file=sys.stdout, flush=True)

    def deltint(self):
        self._pending = None
        self.hold_in("PASSIVE", float("inf"))

    def deltext(self, e):
        vals = list(self.input["observation"].values)
        if vals:
            self._pending = vals[-1]
            self.hold_in("PRINT", 0.0)
        else:
            self.hold_in("PASSIVE", float("inf"))

    def exit(self):
        pass


class System(Coupled):
    def __init__(self, name: str, parent: Optional[Coupled], schedule: List[Tuple[int, float]], max_time: int):
        super().__init__(name)
        self.parent = parent

        # Components
        self.outdoor = OutdoorSchedule("outdoor", parent=self, schedule=schedule)
        self.house = HouseControllerPlant("house", parent=self)
        self.sink = JsonlSink("sink", parent=self, max_time=max_time)

        self.add_component(self.outdoor)
        self.add_component(self.house)
        self.add_component(self.sink)

        # Couplings
        self.add_coupling(self.house.output["req_time"], self.outdoor.input["req_time"])
        self.add_coupling(self.outdoor.output["outdoor_temp"], self.house.input["outdoor_temp"])
        self.add_coupling(self.house.output["observation"], self.sink.input["observation"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate_time", type=float, required=True)
    args = parser.parse_args()

    max_time = int(args.simulate_time)
    schedule = read_outdoor_schedule_from_stdin()

    root = System(name="system", parent=None, schedule=schedule, max_time=max_time)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.simulate_time)


if __name__ == "__main__":
    main()