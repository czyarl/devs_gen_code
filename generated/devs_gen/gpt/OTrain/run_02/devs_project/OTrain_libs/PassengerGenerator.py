import sys
import json
import random
import math
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
        self._passenger_num: int = 0
        self._next_creation_time_s: float | None = None
        self._pending_payload: dict | None = None

    def initialize(self):
        self._passenger_num = 0
        self._pending_payload = None

        if not isinstance(self.station_id, int) or self.station_id not in (1, 2, 3, 4, 5):
            print(
                f"[PassengerGenerator] configuration error: station_id={self.station_id} is outside 1..5",
                file=sys.stderr,
                flush=True,
            )

        if not isinstance(self.station_names, dict) or self.station_id not in self.station_names:
            print(
                f"[PassengerGenerator] configuration error: station_names missing station_id={self.station_id}",
                file=sys.stderr,
                flush=True,
            )

        # Schedule initialization passenger at absolute time init_passenger_time_s.
        now = get_current_time()
        self._next_creation_time_s = float(self.init_passenger_time_s)
        sigma = max(0.0, self._next_creation_time_s - now)
        self.hold_in("EMIT", sigma)

    def deltext(self, e: float):
        # No input ports; autonomous behavior only.
        return None

    def _choose_destination(self) -> int:
        origin = self.station_id
        candidates = [sid for sid in (1, 2, 3, 4, 5) if sid != origin]
        if not candidates:
            # Should never happen with valid origin; fallback to a safe value.
            return 1 if origin != 1 else 2
        return random.choice(candidates)

    def _sample_interarrival_seconds(self) -> int:
        x = random.gauss(self.gen_mean_min, self.gen_std_min)
        if not math.isfinite(x):
            print(
                f"[PassengerGenerator] non-finite interarrival sample {x}; using mean {self.gen_mean_min}",
                file=sys.stderr,
                flush=True,
            )
            x = float(self.gen_mean_min)

        x_clamped = min(max(x, float(self.gen_clamp_min_min)), float(self.gen_clamp_max_min))
        dt_s = int(round(x_clamped * 60.0))
        if dt_s <= 0:
            print(
                f"[PassengerGenerator] non-positive dt_s={dt_s} after rounding; forcing dt_s=1",
                file=sys.stderr,
                flush=True,
            )
            dt_s = 1
        return dt_s

    def _build_passenger_payload(self, t: float, passenger_num: int) -> dict:
        origin = self.station_id
        destination = self._choose_destination()

        if passenger_num == 0:
            passenger_id = 0
        else:
            passenger_id = passenger_num * 100 + origin * 10 + destination

        return {
            "time": t,
            "passenger_id": passenger_id,
            "passenger_num": passenger_num,
            "origin": origin,
            "destination": destination,
        }

    def _write_stdout_event(self, passenger_payload: dict):
        t = float(passenger_payload["time"])
        origin = int(passenger_payload["origin"])

        station_name = None
        if isinstance(self.station_names, dict):
            station_name = self.station_names.get(origin)

        if station_name is None:
            # Avoid emitting malformed stdout events; log to stderr instead.
            print(
                f"[PassengerGenerator] cannot emit stdout event: station name missing for station_id={origin}",
                file=sys.stderr,
                flush=True,
            )
            return

        record = {
            "time": t,
            "event": "passenger_generated",
            "entity_type": "passenger_generator",
            "station_id": origin,
            "station": station_name,
            "payload": {
                "passenger_id": int(passenger_payload["passenger_id"]),
                "passenger_num": int(passenger_payload["passenger_num"]),
                "origin": int(passenger_payload["origin"]),
                "destination": int(passenger_payload["destination"]),
            },
        }
        print(json.dumps(record), flush=True)

    def lambdaf(self):
        if self.phase != "EMIT":
            return

        t = get_current_time()

        # Build the passenger to emit at this internal event time.
        payload = self._build_passenger_payload(t=t, passenger_num=self._passenger_num)
        self._pending_payload = payload

        # DEVS output
        self.output["passenger_out"].add(dict(payload))

        # External IO: stdout JSONL
        self._write_stdout_event(payload)

    def deltint(self):
        if self.phase != "EMIT":
            self.passivate()
            return

        # Schedule next creation time.
        t = get_current_time()

        if self._passenger_num == 0:
            # After init passenger, first stochastic passenger occurs after init time.
            dt_s = self._sample_interarrival_seconds()
            self._next_creation_time_s = float(self.init_passenger_time_s) + float(dt_s)
            self._passenger_num = 1
        else:
            dt_s = self._sample_interarrival_seconds()
            self._next_creation_time_s = float(t) + float(dt_s)
            self._passenger_num += 1

        self._pending_payload = None

        sigma = max(0.0, float(self._next_creation_time_s) - float(t))
        self.hold_in("EMIT", sigma)

    def exit(self):
        pass