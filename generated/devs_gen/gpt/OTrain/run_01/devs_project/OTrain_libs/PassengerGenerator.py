import json
import random
import sys

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class PassengerGenerator(Atomic):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        station_id: int,
        station_names: dict,
        init_passenger_time_s: float,
        gen_mean_min: float,
        gen_std_min: float,
        gen_clamp_min_min: int,
        gen_clamp_max_min: int,
    ):
        super().__init__(name)
        self.parent = parent

        self.station_id = station_id
        self.station_names = station_names

        self.init_passenger_time_s = init_passenger_time_s
        self.gen_mean_min = gen_mean_min
        self.gen_std_min = gen_std_min
        self.gen_clamp_min_min = gen_clamp_min_min
        self.gen_clamp_max_min = gen_clamp_max_min

        self.add_out_port(Port(dict, "passenger_out"))

        # State
        self.passenger_num: int = 0
        self.next_generation_time_s: float = 0.0
        self._pending_passenger_msg: dict | None = None
        self._last_emitted_time: float | None = None

    def initialize(self):
        if not (1 <= int(self.station_id) <= 5):
            print(
                f"[PassengerGenerator:{self.name}] invalid station_id={self.station_id}; expected 1..5",
                file=sys.stderr,
                flush=True,
            )

        if self.station_id not in self.station_names:
            print(
                f"[PassengerGenerator:{self.name}] station_id={self.station_id} not found in station_names",
                file=sys.stderr,
                flush=True,
            )

        self.passenger_num = 0
        self._pending_passenger_msg = None
        self._last_emitted_time = None

        # First generation at fixed time (t=0.5s by contract)
        self.next_generation_time_s = float(self.init_passenger_time_s)
        self.hold_in("GENERATE", max(0.0, self.next_generation_time_s - get_current_time()))

    def deltext(self, e: float):
        # No input ports; no external DEVS messages are processed.
        return None

    def _choose_destination(self) -> int:
        # Uniform among {1..5} \ {origin}
        candidates = [sid for sid in (1, 2, 3, 4, 5) if sid != self.station_id]
        return random.choice(candidates)

    def _sample_interval_seconds_rounded(self) -> int:
        sampled_min = random.gauss(self.gen_mean_min, self.gen_std_min)
        clamped_min = max(float(self.gen_clamp_min_min), min(float(self.gen_clamp_max_min), sampled_min))
        interval_s = clamped_min * 60.0
        interval_s_rounded = int(round(interval_s))
        if interval_s_rounded <= 0:
            interval_s_rounded = 1
        return interval_s_rounded

    def _emit_stdout_event(self, t: float, payload: dict):
        if self._last_emitted_time is not None and t < self._last_emitted_time:
            print(
                f"[PassengerGenerator:{self.name}] WARNING: non-monotone stdout time: {t} < {self._last_emitted_time}",
                file=sys.stderr,
                flush=True,
            )
        self._last_emitted_time = t

        record = {
            "time": float(t),
            "event": "passenger_generated",
            "entity_type": "passenger_generator",
            "station_id": int(self.station_id),
            "station": self.station_names.get(self.station_id, str(self.station_id)),
            "payload": {
                "passenger_id": int(payload["passenger_id"]),
                "passenger_num": int(payload["passenger_num"]),
                "origin": int(payload["origin"]),
                "destination": int(payload["destination"]),
            },
        }
        print(json.dumps(record), flush=True)

    def lambdaf(self):
        if self.phase != "GENERATE":
            return

        t = float(get_current_time())
        destination = self._choose_destination()

        if self.passenger_num == 0:
            passenger_id = 0
        else:
            passenger_id = self.passenger_num * 100 + self.station_id * 10 + destination

        msg = {
            "time": t,
            "passenger_id": int(passenger_id),
            "passenger_num": int(self.passenger_num),
            "origin": int(self.station_id),
            "destination": int(destination),
        }

        # DEVS output
        self.output["passenger_out"].add(dict(msg))

        # External IO (stdout JSONL)
        self._emit_stdout_event(t, msg)

        # Keep for deltint scheduling decisions
        self._pending_passenger_msg = msg

    def deltint(self):
        if self.phase != "GENERATE":
            self.passivate()
            return

        # Advance counter after emitting passenger_num at this time
        self.passenger_num += 1

        # Schedule next generation time based on sampled interval after the init passenger
        interval_s_rounded = self._sample_interval_seconds_rounded()
        self.next_generation_time_s = float(get_current_time()) + float(interval_s_rounded)

        self._pending_passenger_msg = None
        self.hold_in("GENERATE", float(interval_s_rounded))

    def exit(self):
        pass