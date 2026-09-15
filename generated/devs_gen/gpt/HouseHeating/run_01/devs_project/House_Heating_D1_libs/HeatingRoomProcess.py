import json
import sys

from xdevs.models import Atomic, Coupled, Port


class HeatingRoomProcess(Atomic):
    """
    Atomic DEVS model that updates room temperature once per received per-second
    outdoor temperature message and writes one JSONL observation to stdout.
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
        self.add_in_port(Port(dict, "outdoor_temp_c_in"))

        # Parameters
        self.initial_room_temp_c = float(initial_room_temp_c)
        self.initial_control_signal = int(initial_control_signal)
        self.heat_loss_factor = float(heat_loss_factor)
        self.heater_gain_c = float(heater_gain_c)
        self.control_threshold_c = float(control_threshold_c)

        # Persistent state
        self.prev_room_temp_c: float = self.initial_room_temp_c
        self.prev_control_signal: int = self.initial_control_signal

        # Ordering support (nondecreasing stdout order)
        self._pending_by_time: dict[int, float] = {}
        self._next_emit_time: int = 1

    def initialize(self):
        self.prev_room_temp_c = self.initial_room_temp_c
        self.prev_control_signal = self.initial_control_signal
        self._pending_by_time = {}
        self._next_emit_time = 1
        self.passivate("WAITING")

    def deltext(self, e: float):
        # No autonomous time advance; process each received message immediately.
        for msg in self.input["outdoor_temp_c_in"].values:
            try:
                t = int(msg["time_sec"])
                outdoor_temp_c = float(msg["outdoor_temp_c"])
            except Exception as exc:
                print(f"[HeatingRoomProcess] Invalid input message {msg!r}: {exc}", file=sys.stderr, flush=True)
                continue

            # Store and attempt to emit in order.
            if t in self._pending_by_time:
                # Duplicate time; keep the first and warn.
                print(f"[HeatingRoomProcess] Duplicate time_sec={t} received; ignoring later value.", file=sys.stderr, flush=True)
                continue
            self._pending_by_time[t] = outdoor_temp_c

        # Emit as many consecutive times as possible to preserve nondecreasing order.
        while self._next_emit_time in self._pending_by_time:
            t = self._next_emit_time
            outdoor_temp_c = self._pending_by_time.pop(t)

            # Dynamics for time t using previous state (t-1) and scheduled outdoor temp for t.
            effective_outdoor_temp_c = min(outdoor_temp_c, self.prev_room_temp_c)
            heat_loss_temp_c = self.prev_room_temp_c - self.heat_loss_factor * (
                self.prev_room_temp_c - effective_outdoor_temp_c
            )
            heater_output_c = self.heater_gain_c if self.prev_control_signal == 1 else 0.0
            room_temp_c = heat_loss_temp_c + heater_output_c
            control_signal = 1 if room_temp_c < self.control_threshold_c else 0

            # Update state for next step.
            self.prev_room_temp_c = room_temp_c
            self.prev_control_signal = int(control_signal)

            # External IO: exactly one JSONL record per processed second.
            record = {
                "time_sec": int(t),
                "room_temp_c": float(room_temp_c),
                "heat_loss_temp_c": float(heat_loss_temp_c),
                "control_signal": int(control_signal),
                "heater_output_c": float(heater_output_c),
            }
            print(json.dumps(record, separators=(",", ":")), flush=True)

            self._next_emit_time += 1

        self.passivate("WAITING")

    def lambdaf(self):
        # No DEVS output ports for this model.
        pass

    def deltint(self):
        self.passivate("WAITING")

    def exit(self):
        # No required finalization output.
        pass