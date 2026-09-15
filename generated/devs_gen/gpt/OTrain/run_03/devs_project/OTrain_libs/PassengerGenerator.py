import json
import random
import sys
import time
from typing import Any

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class PassengerGenerator(Atomic):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        station_id: int,
        station_ids: list,
        station_names: dict,
        init_time_s: float,
        interarrival_mean_min: float,
        interarrival_std_min: float,
        clamp_min_min: float,
        clamp_max_min: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Configuration (read-only intent)
        self.station_id = station_id
        self.station_ids = station_ids
        self.station_names = station_names
        self.init_time_s = float(init_time_s)
        self.interarrival_mean_min = float(interarrival_mean_min)
        self.interarrival_std_min = float(interarrival_std_min)
        self.clamp_min_min = float(clamp_min_min)
        self.clamp_max_min = float(clamp_max_min)

        # Ports
        self.add_out_port(Port(dict, "passenger_out"))

        # State
        self.passenger_num: int = 0  # 0 reserved for initialization passenger
        self.next_gen_time_s: float = 0.0  # absolute simulation time
        self._pending_passenger: dict[str, Any] | None = None
        self._pending_event_time_s: float | None = None

    def initialize(self):
        # Seed RNG using system time (affects only stochastic choices).
        random.seed(time.time_ns())

        self.passenger_num = 0
        self._pending_passenger = None
        self._pending_event_time_s = None

        # Schedule first generation at absolute time init_time_s.
        self.next_gen_time_s = max(0.0, float(self.init_time_s))
        now = float(get_current_time())
        sigma = self.next_gen_time_s - now
        if sigma < 0.0:
            # If simulator starts after init_time_s for any reason, emit immediately.
            sigma = 0.0
        self.hold_in("GENERATE", sigma)

    def deltext(self, e: float):
        # No input ports; ignore all external DEVS messages.
        return None

    def _choose_destination(self) -> int | None:
        origin = self.station_id
        if origin not in self.station_ids:
            print(
                f"WARNING PassengerGenerator(station_id={origin}): origin not in station_ids={self.station_ids}; skipping passenger generation attempt.",
                file=sys.stderr,
                flush=True,
            )
            return None

        candidates = [sid for sid in self.station_ids if sid != origin]
        if not candidates:
            print(
                f"WARNING PassengerGenerator(station_id={origin}): no alternative destinations in station_ids={self.station_ids}; skipping passenger generation attempt.",
                file=sys.stderr,
                flush=True,
            )
            return None

        # Uniform among other stations.
        dest = random.choice(candidates)
        if dest == origin:
            # Defensive: should not happen due to filtering.
            for _ in range(10):
                dest = random.choice(candidates)
                if dest != origin:
                    break
            if dest == origin:
                print(
                    f"WARNING PassengerGenerator(station_id={origin}): destination selection failed to avoid origin; skipping passenger generation attempt.",
                    file=sys.stderr,
                    flush=True,
                )
                return None
        return int(dest)

    def _sample_next_delay_seconds(self) -> int:
        x = random.normalvariate(self.interarrival_mean_min, self.interarrival_std_min)
        if x < self.clamp_min_min:
            x = self.clamp_min_min
        elif x > self.clamp_max_min:
            x = self.clamp_max_min

        dt_s = x * 60.0
        dt_round_s = int(round(dt_s))
        if dt_round_s <= 0:
            dt_round_s = 1
        return dt_round_s

    def _prepare_generation_at(self, t_gen: float):
        # Determine initialization passenger vs normal passenger.
        is_init = (t_gen == float(self.init_time_s)) and (self.passenger_num == 0)

        destination = self._choose_destination()
        if destination is None:
            # No passenger emitted; schedule next attempt using normal inter-arrival logic.
            dt_round_s = self._sample_next_delay_seconds()
            self.next_gen_time_s = float(t_gen) + float(dt_round_s)
            self._pending_passenger = None
            self._pending_event_time_s = None
            return

        origin = int(self.station_id)

        if is_init:
            passenger_num = 0
            passenger_id = 0
        else:
            self.passenger_num += 1
            passenger_num = int(self.passenger_num)
            passenger_id = int(passenger_num * 100 + origin * 10 + int(destination))

        passenger = {
            "passenger_id": int(passenger_id),
            "passenger_num": int(passenger_num),
            "origin": int(origin),
            "destination": int(destination),
        }

        self._pending_passenger = passenger
        self._pending_event_time_s = float(t_gen)

        # Schedule next generation time after emitting this passenger.
        dt_round_s = self._sample_next_delay_seconds()
        self.next_gen_time_s = float(t_gen) + float(dt_round_s)

    def lambdaf(self):
        if self.phase != "GENERATE":
            return

        # The event time is the current simulation time when lambdaf runs.
        t_gen = float(get_current_time())

        # Prepare passenger and next schedule if not already prepared for this event time.
        # (Normally not prepared earlier; this keeps lambdaf self-contained and correct.)
        self._prepare_generation_at(t_gen)

        if self._pending_passenger is None or self._pending_event_time_s is None:
            return

        # DEVS output
        self.output["passenger_out"].add(dict(self._pending_passenger))

        # Stdout JSONL event record (must be valid JSON only)
        station_str = self.station_names.get(self.station_id)
        if station_str is None:
            # Best-effort per contract; scenario provides full mapping.
            station_str = str(self.station_id)

        record = {
            "time": float(self._pending_event_time_s),
            "event": "passenger_generated",
            "entity_type": "passenger_generator",
            "station_id": int(self.station_id),
            "station": str(station_str),
            "payload": {
                "passenger_id": int(self._pending_passenger["passenger_id"]),
                "passenger_num": int(self._pending_passenger["passenger_num"]),
                "origin": int(self._pending_passenger["origin"]),
                "destination": int(self._pending_passenger["destination"]),
            },
        }
        print(json.dumps(record), flush=True)

    def deltint(self):
        if self.phase != "GENERATE":
            self.passivate()
            return

        # Clear pending emission state (if any)
        self._pending_passenger = None
        self._pending_event_time_s = None

        # Schedule next internal event based on absolute next_gen_time_s
        now = float(get_current_time())
        sigma = float(self.next_gen_time_s) - now
        if sigma < 0.0:
            sigma = 0.0
        self.hold_in("GENERATE", sigma)

    def exit(self):
        # No required shutdown behavior.
        pass