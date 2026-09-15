#!/usr/bin/env python3
import sys
import json
import argparse
from dataclasses import dataclass
from typing import List, Tuple, Optional

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock


def _parse_hhmmss_to_seconds(s: str) -> int:
    parts = s.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid HH:MM:SS timestamp: {s!r}")
    hh, mm, ss = (int(p) for p in parts)
    return hh * 3600 + mm * 60 + ss


class OutdoorSchedule:
    """Piecewise-constant schedule: for time t, use reading with greatest timestamp <= t."""
    def __init__(self, readings: List[Tuple[int, float]]):
        # Ensure sorted by timestamp
        self.readings = sorted(readings, key=lambda x: x[0])

    @staticmethod
    def from_stdin(stdin) -> "OutdoorSchedule":
        readings: List[Tuple[int, float]] = []
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            # Expected: "HH:MM:SS temp"
            parts = line.split()
            if len(parts) < 2:
                continue
            ts = _parse_hhmmss_to_seconds(parts[0])
            temp = float(parts[1])
            readings.append((ts, temp))
        return OutdoorSchedule(readings)

    def get(self, t: float) -> float:
        # Default if no reading <= t
        if not self.readings:
            return 25.0
        # Binary search for rightmost timestamp <= t
        lo, hi = 0, len(self.readings) - 1
        if self.readings[0][0] > t:
            return 25.0
        while lo <= hi:
            mid = (lo + hi) // 2
            if self.readings[mid][0] <= t:
                lo = mid + 1
            else:
                hi = mid - 1
        return self.readings[hi][1]


@dataclass(frozen=True)
class Observation:
    time_sec: int
    room_temp_c: float
    heat_loss_temp_c: float
    control_signal: int
    heater_output_c: float


class HeaterRoomController(Atomic):
    """
    Single atomic model that advances in 1-second steps and emits an Observation each step.
    Observation times: 1..N (integer seconds).
    """
    def __init__(self, name: str, parent: Optional[Coupled], schedule: OutdoorSchedule, simulate_time: float):
        super().__init__(name)
        self.parent = parent
        self.schedule = schedule
        self.simulate_time = simulate_time

        self.add_out_port(Port(Observation, "obs"))

        # State
        self.t: int = 0  # current integer time (observation index already produced)
        self.room_temp: float = 25.0
        self.control_signal: int = 0  # control_signal[0] = 0
        self.next_obs: Optional[Observation] = None

        # Start immediately
        self.hold_in("INIT", 0)

    def initialize(self):
        self.t = 0
        self.room_temp = 25.0
        self.control_signal = 0
        self.next_obs = None
        # Schedule first step at +1 second (to produce observation at t=1)
        self.hold_in("STEP", 1.0)

    def lambdaf(self):
        if self.next_obs is not None:
            self.output["obs"].add(self.next_obs)

    def deltint(self):
        # Internal transition at each second boundary: compute next state and prepare output
        # We are at time self.t (already produced obs for t), now advancing to t+1
        next_t = self.t + 1

        # Use outdoor temperature from previous second (time next_t-1)
        outdoor = self.schedule.get(next_t - 1)
        effective_outdoor = min(outdoor, self.room_temp)  # cap to prevent outdoor heat gain

        # Apply heat loss: lose 10% of gap to effective outdoor
        heat_loss_temp = self.room_temp - 0.1 * (self.room_temp - effective_outdoor)

        # Heater gain delayed by one step: based on previous control signal
        heater_output = 0.5 if self.control_signal == 1 else 0.0
        new_room_temp = heat_loss_temp + heater_output

        # Controller sets next control signal based on new room temperature
        next_control = 1 if new_room_temp < 24.9 else 0

        # Prepare observation for time next_t (must reflect updated state and next control)
        self.next_obs = Observation(
            time_sec=next_t,
            room_temp_c=float(new_room_temp),
            heat_loss_temp_c=float(heat_loss_temp),
            control_signal=int(next_control),
            heater_output_c=float(heater_output),
        )

        # Commit state
        self.t = next_t
        self.room_temp = new_room_temp
        self.control_signal = next_control

        # Schedule next step if within required horizon; otherwise go passive
        if self.t < int(self.simulate_time):
            self.hold_in("STEP", 1.0)
        else:
            self.hold_in("DONE", float("inf"))

    def deltext(self, e):
        # No external inputs in this model; remain in current phase.
        # Still must implement.
        self.hold_in(self.phase, self.sigma)

    def exit(self):
        pass


class System(Coupled):
    def __init__(self, name: str, parent: Optional[Coupled], schedule: OutdoorSchedule, simulate_time: float):
        super().__init__(name)
        self.parent = parent

        self.add_out_port(Port(Observation, "obs"))

        model = HeaterRoomController("heater_room_controller", parent=self, schedule=schedule, simulate_time=simulate_time)
        self.add_component(model)

        self.add_coupling(model.output["obs"], self.output["obs"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate_time", type=float, required=True)
    args = parser.parse_args()

    simulate_time = args.simulate_time
    if simulate_time < 0:
        raise SystemExit("--simulate_time must be non-negative")

    schedule = OutdoorSchedule.from_stdin(sys.stdin)

    root = System(name="system", parent=None, schedule=schedule, simulate_time=simulate_time)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()

    # Run simulation
    coord.simulate_time(simulate_time)

    # Collect and print observations from the coupled output port.
    # xdevs does not automatically print; we must retrieve emitted events.
    #
    # However, xdevs Coordinator typically routes outputs during simulation.
    # To ensure we print exactly one JSON per second, we re-run the same deterministic
    # dynamics here would violate "only JSONL to stdout" if we printed during sim.
    #
    # Instead, we print during simulation by attaching a lightweight "sink" atomic model.
    # But requirement says only JSONL to stdout; that's fine. We'll implement sink below.
    #
    # Note: The above simulate_time already ran without sink; so no outputs printed.
    # We'll therefore implement sink and run once, printing in real-time.
    #
    # To keep the program correct, we rebuild with sink and rerun once for actual output.
    #
    # (This avoids relying on internal Coordinator output storage specifics.)

    # Rebuild system with sink and rerun for output
    class JsonlSink(Atomic):
        def __init__(self, name: str, parent: Optional[Coupled], simulate_time: float):
            super().__init__(name)
            self.parent = parent
            self.simulate_time = simulate_time
            self.add_in_port(Port(Observation, "in_obs"))
            self.hold_in("PASSIVE", float("inf"))

        def initialize(self):
            self.hold_in("PASSIVE", float("inf"))

        def lambdaf(self):
            # No outputs
            return

        def deltint(self):
            self.hold_in("PASSIVE", float("inf"))

        def deltext(self, e):
            # Print all received observations
            vals = list(self.input["in_obs"].values)
            for obs in vals:
                if 1 <= obs.time_sec <= int(self.simulate_time):
                    rec = {
                        "time_sec": int(obs.time_sec),
                        "room_temp_c": float(obs.room_temp_c),
                        "heat_loss_temp_c": float(obs.heat_loss_temp_c),
                        "control_signal": int(obs.control_signal),
                        "heater_output_c": float(obs.heater_output_c),
                    }
                    print(json.dumps(rec, separators=(",", ":")), file=sys.stdout, flush=True)
            self.hold_in("PASSIVE", float("inf"))

        def exit(self):
            pass

    class SystemWithSink(Coupled):
        def __init__(self, name: str, parent: Optional[Coupled], schedule: OutdoorSchedule, simulate_time: float):
            super().__init__(name)
            self.parent = parent
            ctrl = HeaterRoomController("heater_room_controller", parent=self, schedule=schedule, simulate_time=simulate_time)
            sink = JsonlSink("jsonl_sink", parent=self, simulate_time=simulate_time)
            self.add_component(ctrl)
            self.add_component(sink)
            self.add_coupling(ctrl.output["obs"], sink.input["in_obs"])

    root2 = SystemWithSink(name="system", parent=None, schedule=schedule, simulate_time=simulate_time)
    coord2 = Coordinator(root2, clock=SimulationClock(0))
    coord2.initialize()
    coord2.simulate_time(simulate_time)


if __name__ == "__main__":
    main()