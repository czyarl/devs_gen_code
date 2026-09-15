"""HouseHeatingProcess: input-driven atomic DEVS model that writes JSONL observations to stdout."""

import json
import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class HouseHeatingProcess(Atomic):
    """
    Purely input-driven process:
    - Receives one message per integer second t=1..int(simulation_time) on outdoor_temp_in
      with format: {'time_sec': int, 'outdoor_temp_c': float}
    - Advances exactly one step when (and only when) t == last_time_sec + 1
    - Writes exactly one JSONL record to stdout per accepted message.
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        initial_room_temp_c: float,
        initial_control_signal: int,
        heat_loss_factor: float,
        heater_gain_c: float,
        control_threshold_c: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Ports (locked contract)
        self.add_in_port(Port(dict, "outdoor_temp_in"))

        # Parameters (constants for the run)
        self.initial_room_temp_c = float(initial_room_temp_c)
        self.initial_control_signal = int(initial_control_signal)
        self.heat_loss_factor = float(heat_loss_factor)
        self.heater_gain_c = float(heater_gain_c)
        self.control_threshold_c = float(control_threshold_c)

        # Retained state (initialized in initialize())
        self.last_time_sec: int = 0
        self.room_temp_c: float = self.initial_room_temp_c
        self.control_signal: int = self.initial_control_signal

    def initialize(self):
        # Startup behavior at simulation time 0: set retained state, no output.
        self.last_time_sec = 0
        self.room_temp_c = self.initial_room_temp_c
        self.control_signal = self.initial_control_signal
        self.passivate("WAITING")

    def deltext(self, e: float):
        # No autonomous clock; process each received driving schedule message.
        for msg in self.input["outdoor_temp_in"].values:
            if not isinstance(msg, dict):
                print(
                    f"[HouseHeatingProcess] Ignoring non-dict message at sim_time={get_current_time()}: {msg!r}",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            try:
                t = int(msg["time_sec"])
                scheduled_outdoor_temp = float(msg["outdoor_temp_c"])
            except Exception as exc:
                print(
                    f"[HouseHeatingProcess] Ignoring malformed message at sim_time={get_current_time()}: {msg!r} ({exc})",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            # Ordering rules
            if t <= self.last_time_sec:
                # Stale/duplicate: ignore silently (optional stderr diagnostics allowed)
                continue

            if t != self.last_time_sec + 1:
                # Gap: cannot synthesize missing steps without intervening outdoor temps
                print(
                    f"[HouseHeatingProcess] Gap detected: received time_sec={t} but expected {self.last_time_sec + 1}. Ignoring.",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            # One-step deterministic update from retained state at time (t-1)
            prev_room_temp_c = self.room_temp_c
            prev_control_signal = self.control_signal

            effective_outdoor_temp = min(scheduled_outdoor_temp, prev_room_temp_c)

            heat_loss_temp_c = prev_room_temp_c - self.heat_loss_factor * (
                prev_room_temp_c - effective_outdoor_temp
            )

            heater_output_c = self.heater_gain_c if prev_control_signal == 1 else 0.0

            room_temp_c = heat_loss_temp_c + heater_output_c

            next_control_signal = 1 if room_temp_c < self.control_threshold_c else 0

            # Commit retained state
            self.last_time_sec = t
            self.room_temp_c = room_temp_c
            self.control_signal = int(next_control_signal)

            # External IO: exactly one compact JSON object per accepted message (JSONL)
            print(
                json.dumps(
                    {
                        "time_sec": int(t),
                        "room_temp_c": float(room_temp_c),
                        "heat_loss_temp_c": float(heat_loss_temp_c),
                        "control_signal": int(next_control_signal),
                        "heater_output_c": float(heater_output_c),
                    }
                ),
                flush=True,
            )

        # Always wait for next input; no DEVS output ports.
        self.passivate("WAITING")

    def lambdaf(self):
        # No DEVS output ports; stdout is written in deltext() per contract pattern.
        pass

    def deltint(self):
        # No internal transitions scheduled.
        self.passivate("WAITING")

    def exit(self):
        # No special termination action.
        pass