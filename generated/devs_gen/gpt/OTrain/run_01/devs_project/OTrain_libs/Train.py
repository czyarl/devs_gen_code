import json
import sys
from collections import defaultdict

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class Train(Atomic):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        station_names: dict,
        travel_time_s: int,
        route_sequence: list,
        initial_arrival_time_s: float,
        service_dt_s: float,
    ):
        super().__init__(name)
        self.parent = parent

        self.station_names = station_names
        self.travel_time_s = travel_time_s
        self.route_sequence = route_sequence
        self.initial_arrival_time_s = initial_arrival_time_s
        self.service_dt_s = service_dt_s

        self.add_in_port(Port(dict, "boarded_in"))
        self.add_out_port(Port(dict, "arrival_out"))

        # Remembered state
        self.route_index: int = 0
        self.next_arrival_time: float = 0.0
        self.onboard_by_destination: dict[int, list[dict]] = defaultdict(list)

        # Pending alighting batch state
        self.alight_station_id: int | None = None
        self.alight_base_time: float | None = None
        self.alight_list: list[dict] = []
        self.alight_cursor: int = 0

        # Output preparation
        self._pending_arrival_msg: dict | None = None
        self._pending_stdout_record: dict | None = None

        self.last_emitted_time: float = -1.0

    def initialize(self):
        self.route_index = 0
        self.next_arrival_time = float(self.initial_arrival_time_s)

        self.onboard_by_destination = defaultdict(list)

        self.alight_station_id = None
        self.alight_base_time = None
        self.alight_list = []
        self.alight_cursor = 0

        self._pending_arrival_msg = None
        self._pending_stdout_record = None
        self.last_emitted_time = -1.0

        # Schedule first arrival (including t=0.0)
        self.hold_in("ARRIVAL", max(0.0, self.next_arrival_time - get_current_time()))

    def deltext(self, e: float):
        # Process boarded passengers at any time.
        for msg in self.input["boarded_in"].values:
            try:
                destination = int(msg["destination"])
                origin = int(msg["origin"])
                passenger_id = int(msg["passenger_id"])
                passenger_num = int(msg["passenger_num"])
                # 'time' is for diagnostics only
                _t = msg.get("time", None)
            except Exception as ex:
                print(f"[Train] Ignoring malformed boarded_in message: {msg} ({ex})", file=sys.stderr, flush=True)
                continue

            if destination not in (1, 2, 3, 4, 5) or origin not in (1, 2, 3, 4, 5) or destination == origin:
                print(
                    f"[Train] Ignoring invalid boarded passenger: passenger_id={passenger_id} "
                    f"origin={origin} destination={destination} time={_t}",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            passenger = {
                "passenger_id": passenger_id,
                "passenger_num": passenger_num,
                "origin": origin,
                "destination": destination,
            }
            self.onboard_by_destination[destination].append(passenger)

        # Preserve remaining time to next internal event
        self.continuef(e)

    def _stdout_emit(self, record: dict):
        t = float(record.get("time", 0.0))
        if t < self.last_emitted_time:
            print(
                f"[Train] WARNING: stdout time decreased: last={self.last_emitted_time} new={t} record={record}",
                file=sys.stderr,
                flush=True,
            )
        self.last_emitted_time = max(self.last_emitted_time, t)
        print(json.dumps(record), flush=True)

    def _prepare_arrival_outputs(self, T: float):
        stop = self.route_sequence[self.route_index]
        station_id = int(stop["station_id"])
        direction = int(stop["direction"])
        station_name = self.station_names[station_id]

        # Stdout JSONL record
        self._pending_stdout_record = {
            "time": float(T),
            "event": "train_arrival",
            "entity_type": "train",
            "station_id": station_id,
            "station": station_name,
            "payload": {"station": station_id, "direction": direction},
        }

        # DEVS output message
        self._pending_arrival_msg = {"time": float(T), "station_id": station_id, "direction": direction}

        # Snapshot alighting list and remove from onboard immediately
        self.alight_station_id = station_id
        self.alight_base_time = float(T)
        self.alight_list = list(self.onboard_by_destination.get(station_id, []))
        if station_id in self.onboard_by_destination:
            del self.onboard_by_destination[station_id]
        self.alight_cursor = 0

        # Schedule next arrival now (state remembered)
        self.route_index = (self.route_index + 1) % len(self.route_sequence)
        self.next_arrival_time = float(T + self.travel_time_s)

    def _prepare_alight_stdout_record(self, Te: float):
        passenger = self.alight_list[self.alight_cursor]
        station_id = int(self.alight_station_id)
        station_name = self.station_names[station_id]
        self._pending_stdout_record = {
            "time": float(Te),
            "event": "passenger_exiting",
            "entity_type": "train_queue",
            "station_id": station_id,
            "station": station_name,
            "payload": {
                "passenger_id": int(passenger["passenger_id"]),
                "passenger_num": int(passenger["passenger_num"]),
                "origin": int(passenger["origin"]),
                "destination": int(passenger["destination"]),
            },
        }

    def lambdaf(self):
        now = float(get_current_time())

        if self.phase == "ARRIVAL":
            # Prepare and emit arrival outputs at time now
            self._prepare_arrival_outputs(now)

            if self._pending_arrival_msg is not None:
                self.output["arrival_out"].add(dict(self._pending_arrival_msg))

            if self._pending_stdout_record is not None:
                self._stdout_emit(self._pending_stdout_record)

            return

        if self.phase == "ALIGHT":
            # Emit one passenger_exiting record at its computed time.
            # The internal scheduling ensures now == base + (cursor+1)*dt.
            self._prepare_alight_stdout_record(now)
            if self._pending_stdout_record is not None:
                self._stdout_emit(self._pending_stdout_record)
            return

    def deltint(self):
        now = float(get_current_time())

        if self.phase == "ARRIVAL":
            # Clear prepared outputs
            self._pending_arrival_msg = None
            self._pending_stdout_record = None

            # After arrival, either start alighting (first at +dt) or wait for next arrival.
            if self.alight_list and self.alight_cursor < len(self.alight_list):
                self.hold_in("ALIGHT", float(self.service_dt_s))
            else:
                # No alighting; clear batch state
                self.alight_station_id = None
                self.alight_base_time = None
                self.alight_list = []
                self.alight_cursor = 0

                sigma = max(0.0, float(self.next_arrival_time - now))
                self.hold_in("ARRIVAL", sigma)
            return

        if self.phase == "ALIGHT":
            # Finished emitting one alighting record
            self._pending_stdout_record = None

            self.alight_cursor += 1
            if self.alight_cursor < len(self.alight_list):
                self.hold_in("ALIGHT", float(self.service_dt_s))
            else:
                # Clear batch state and proceed to next arrival
                self.alight_station_id = None
                self.alight_base_time = None
                self.alight_list = []
                self.alight_cursor = 0

                sigma = max(0.0, float(self.next_arrival_time - now))
                self.hold_in("ARRIVAL", sigma)
            return

        # Fallback: if somehow in another phase, ensure we keep moving.
        sigma = max(0.0, float(self.next_arrival_time - now))
        self.hold_in("ARRIVAL", sigma)

    def exit(self):
        pass