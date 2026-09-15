from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterator, TextIO

import simpy

from house_heating.schedule import OutdoorTempSchedule


@dataclass(frozen=True)
class SimulationConfig:
    total_seconds: int


class HouseHeatingDES:
    def __init__(self, env: simpy.Environment, *, cfg: SimulationConfig, schedule: OutdoorTempSchedule):
        self.env = env
        self.cfg = cfg
        self.schedule = schedule

        self.room_temp_c: float = 25.0
        self.control_signal: int = 0  # control_signal[0]

        self.records: simpy.Store[str] = simpy.Store(env)

    def _step(self) -> str:
        prev_temp = self.room_temp_c
        prev_control = self.control_signal

        outdoor = self.schedule.get_outdoor_temp(int(self.env.now) - 1)
        outdoor_eff = min(outdoor, prev_temp)

        heat_loss_temp = prev_temp - 0.1 * (prev_temp - outdoor_eff)
        heater_output = 0.5 if prev_control == 1 else 0.0
        new_temp = heat_loss_temp + heater_output

        next_control = 1 if new_temp < 24.9 else 0

        t = int(self.env.now)
        record = {
            "time_sec": t,
            "room_temp_c": float(new_temp),
            "heat_loss_temp_c": float(heat_loss_temp),
            "control_signal": int(next_control),
            "heater_output_c": float(heater_output),
        }

        self.room_temp_c = new_temp
        self.control_signal = next_control
        return json.dumps(record, separators=(",", ":"))

    def run(self):
        while self.env.now < self.cfg.total_seconds:
            yield self.env.timeout(1)
            rec = self._step()
            self.records.put(rec)


def run_simulation(*, cfg: SimulationConfig, schedule: OutdoorTempSchedule, debug_stream: TextIO) -> Iterator[str]:
    if cfg.total_seconds < 0:
        raise ValueError("total_seconds must be non-negative")

    env = simpy.Environment()
    model = HouseHeatingDES(env, cfg=cfg, schedule=schedule)
    env.process(model.run())

    for _ in range(cfg.total_seconds):
        rec = env.run(until=model.records.get())
        yield rec
