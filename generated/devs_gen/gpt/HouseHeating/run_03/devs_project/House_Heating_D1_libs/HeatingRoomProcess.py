import json
import math
import sys

from xdevs.models import Atomic, Coupled, Port


class HeatingRoomProcess(Atomic):
    """
    Atomic DEVS model: advances heated-room dynamics exactly one whole second
    per received input message on scheduled_outdoor_temp_in, and writes one JSONL
    observation per accepted step to stdout.

    Notes:
    - No DEVS output ports are used; observability is via stdout JSONL.
    - Never reads stdin.
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulate_time: float,
        target_temp_c: float,
        heat_loss_rate: float,
        heater_gain_c: float,
        initial_room_temp_c: float,
        initial_control_signal: int,
    ):
        super().__init__(name)
        self.parent = parent

        # Parameters
        self.simulate_time = float(simulate_time)
        self.target_temp_c = float(target_temp_c)
        self.heat_loss_rate = float(heat_loss_rate)
        self.heater_gain_c = float(heater_gain_c)
        self.initial_room_temp_c = float(initial_room_temp_c)
        self.initial_control_signal = int(initial_control_signal)

        # Ports
        self.add_in_port(Port(dict, "scheduled_outdoor_temp_in"))

        # Retained state
        self.prev_room_temp_c: float = self.initial_room_temp_c
        self.prev_control_signal: int = self.initial_control_signal
        self.last_emitted_time_sec: int = 0

    def initialize(self):
        self.prev_room_temp_c = self.initial_room_temp_c
        self.prev_control_signal = int(self.initial_control_signal)
        self.last_emitted_time_sec = 0
        self.passivate("WAITING")

    def deltext(self, e: float):
        max_t = int(self.simulate_time)

        for msg in self.input["scheduled_outdoor_temp_in"].values:
            if self.last_emitted_time_sec >= max_t:
                # Effectively passive after completing required outputs.
                continue

            if not isinstance(msg, dict):
                print(
                    f"[HeatingRoomProcess] Invalid input type {type(msg)}; expected dict. Skipping.",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            if "time_sec" not in msg or "scheduled_outdoor_temp_c" not in msg:
                print(
                    f"[HeatingRoomProcess] Missing required keys in input {msg}. Skipping.",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            try:
                t = int(msg["time_sec"])
            except Exception:
                print(
                    f"[HeatingRoomProcess] Invalid time_sec in input {msg}. Skipping.",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            # Enforce monotonic, exactly-once discipline for stdout.
            if t <= self.last_emitted_time_sec:
                print(
                    f"[HeatingRoomProcess] Non-increasing time_sec={t} (last_emitted={self.last_emitted_time_sec}); skipping emit and state advance.",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            if t > max_t:
                print(
                    f"[HeatingRoomProcess] time_sec={t} exceeds int(simulate_time)={max_t}; ignoring without state advance.",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            try:
                scheduled_outdoor = float(msg["scheduled_outdoor_temp_c"])
            except Exception:
                print(
                    f"[HeatingRoomProcess] Invalid scheduled_outdoor_temp_c in input {msg}. Skipping.",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            if not math.isfinite(scheduled_outdoor):
                print(
                    f"[HeatingRoomProcess] Non-finite scheduled_outdoor_temp_c={scheduled_outdoor} at time_sec={t}; skipping.",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            prev_room = float(self.prev_room_temp_c)
            prev_control = int(self.prev_control_signal)

            # 1) Effective outdoor temperature (no outdoor heat gain)
            effective_outdoor = min(scheduled_outdoor, prev_room)

            # 2) Heat-loss update
            heat_loss_temp_c = prev_room - self.heat_loss_rate * (prev_room - effective_outdoor)

            # 3) One-step-delayed heater gain
            heater_output_c = self.heater_gain_c if prev_control == 1 else 0.0

            # 4) New room temperature
            room_temp_c = heat_loss_temp_c + heater_output_c

            # 5) Controller update for next step
            control_signal = 1 if room_temp_c < self.target_temp_c else 0
            control_signal = int(control_signal)

            record = {
                "time_sec": int(t),
                "room_temp_c": float(room_temp_c),
                "heat_loss_temp_c": float(heat_loss_temp_c),
                "control_signal": int(control_signal),
                "heater_output_c": float(heater_output_c),
            }

            # External IO: stdout JSONL only
            print(json.dumps(record), flush=True)

            # State update after emitting
            self.prev_room_temp_c = float(room_temp_c)
            self.prev_control_signal = int(control_signal)
            self.last_emitted_time_sec = int(t)

        self.passivate("WAITING")

    def lambdaf(self):
        # No DEVS output ports are used by this model.
        pass

    def deltint(self):
        self.passivate("WAITING")

    def exit(self):
        pass