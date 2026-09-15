import sys
import json

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class Aircraft(Atomic):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        aircraft_id: int,
        flight_time: float,
        unload_time: float,
        return_time: float,
        maintenance_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        self.aircraft_id = int(aircraft_id)
        self.flight_time = float(flight_time)
        self.unload_time = float(unload_time)
        self.return_time = float(return_time)
        self.maintenance_time = float(maintenance_time)

        self.add_in_port(Port(dict, "assignment_in"))
        self.add_out_port(Port(dict, "idle_out"))
        self.add_out_port(Port(dict, "delivered_out"))

        # Retained job context while busy
        self.current_pallet_id: int | None = None
        self.current_generation_time: float | None = None

        # Immediate output set for the next internal event
        self._pending_idle_out: dict | None = None
        self._pending_delivered_out: dict | None = None
        self._pending_stdout_records: list[dict] = []

    def initialize(self):
        self.current_pallet_id = None
        self.current_generation_time = None
        self._clear_pending_outputs()

        # Must emit idle_out at t=0.0 (via lambdaf)
        self._pending_idle_out = {"aircraft_id": self.aircraft_id}
        self.hold_in("INITIALIZING", 0.0)

    def deltext(self, e: float):
        was_busy = self.phase != "IDLE"
        remaining = max(0.0, self.ta() - e) if was_busy else None

        accepted = False
        if not was_busy:
            for msg in self.input["assignment_in"].values:
                try:
                    msg_aircraft_id = msg.get("aircraft_id", None)
                except AttributeError:
                    continue

                if msg_aircraft_id != self.aircraft_id:
                    continue

                # Accept exactly one matching assignment (first in bag/order)
                try:
                    self.current_pallet_id = int(msg["pallet_id"])
                    self.current_generation_time = float(msg["generation_time"])
                except Exception as ex:
                    print(
                        f"Aircraft {self.aircraft_id}: invalid assignment ignored: {msg!r} ({ex})",
                        file=sys.stderr,
                        flush=True,
                    )
                    self.current_pallet_id = None
                    self.current_generation_time = None
                    continue

                now = get_current_time()
                self._pending_stdout_records.append(
                    {
                        "time": now,
                        "entity": "aircraft",
                        "event": "depart",
                        "payload": {
                            "aircraft_id": self.aircraft_id,
                            "pallet_id": self.current_pallet_id,
                        },
                    }
                )
                accepted = True
                break

            if accepted:
                # Loading is instantaneous; depart is at acceptance time.
                # Transition immediately into outbound flight phase.
                self.hold_in("DEPART_OUTPUT", 0.0)
            else:
                # Remain idle awaiting assignments
                self.passivate("IDLE")
        else:
            # Busy: ignore all assignments (including matching ones), preserve deadline
            # Optional diagnostics to stderr only
            for msg in self.input["assignment_in"].values:
                try:
                    if msg.get("aircraft_id", None) == self.aircraft_id:
                        print(
                            f"Aircraft {self.aircraft_id}: assignment ignored while busy at t={get_current_time()}",
                            file=sys.stderr,
                            flush=True,
                        )
                        break
                except AttributeError:
                    continue

            if remaining is not None:
                self.hold_in(self.phase, remaining)

    def lambdaf(self):
        # DEVS outputs must be emitted only here
        if self._pending_idle_out is not None:
            self.output["idle_out"].add(dict(self._pending_idle_out))

        if self._pending_delivered_out is not None:
            self.output["delivered_out"].add(dict(self._pending_delivered_out))

        # External IO: stdout JSONL lifecycle records
        if self._pending_stdout_records:
            for record in self._pending_stdout_records:
                print(json.dumps(record), flush=True)

    def deltint(self):
        # Clear any outputs that were just emitted
        self._clear_pending_outputs()

        if self.phase == "INITIALIZING":
            self.passivate("IDLE")

        elif self.phase == "DEPART_OUTPUT":
            # After depart record at t_a, start outbound flight
            self.hold_in("FLYING_OUT", max(0.0, self.flight_time))

        elif self.phase == "FLYING_OUT":
            self.hold_in("UNLOADING", max(0.0, self.unload_time))

        elif self.phase == "UNLOADING":
            # Delivery at unload completion time
            if self.current_pallet_id is not None and self.current_generation_time is not None:
                self._pending_delivered_out = {
                    "aircraft_id": self.aircraft_id,
                    "pallet_id": self.current_pallet_id,
                    "generation_time": self.current_generation_time,
                }
            else:
                print(
                    f"Aircraft {self.aircraft_id}: unload completed with no current pallet context at t={get_current_time()}",
                    file=sys.stderr,
                    flush=True,
                )

            # Emit delivered_out at this same time, then transition to returning
            self.hold_in("DELIVERY_OUTPUT", 0.0)

        elif self.phase == "DELIVERY_OUTPUT":
            self.hold_in("RETURNING", max(0.0, self.return_time))

        elif self.phase == "RETURNING":
            # At return completion time t_r, write two stdout records in order:
            now = get_current_time()
            self._pending_stdout_records.append(
                {
                    "time": now,
                    "entity": "aircraft",
                    "event": "return",
                    "payload": {"aircraft_id": self.aircraft_id},
                }
            )
            self._pending_stdout_records.append(
                {
                    "time": now,
                    "entity": "aircraft",
                    "event": "maintenance_start",
                    "payload": {"aircraft_id": self.aircraft_id},
                }
            )
            self.hold_in("RETURN_AND_MAINT_START_OUTPUT", 0.0)

        elif self.phase == "RETURN_AND_MAINT_START_OUTPUT":
            self.hold_in("MAINTENANCE", max(0.0, self.maintenance_time))

        elif self.phase == "MAINTENANCE":
            # At maintenance completion time t_m:
            now = get_current_time()
            self._pending_stdout_records.append(
                {
                    "time": now,
                    "entity": "aircraft",
                    "event": "maintenance_end",
                    "payload": {"aircraft_id": self.aircraft_id},
                }
            )
            # Clear job context and become idle; emit idle_out at same time
            self.current_pallet_id = None
            self.current_generation_time = None
            self._pending_idle_out = {"aircraft_id": self.aircraft_id}
            self.hold_in("MAINT_END_OUTPUT", 0.0)

        elif self.phase == "MAINT_END_OUTPUT":
            self.passivate("IDLE")

        else:
            # Fallback: become idle
            self.passivate("IDLE")

    def exit(self):
        pass

    def _clear_pending_outputs(self):
        self._pending_idle_out = None
        self._pending_delivered_out = None
        self._pending_stdout_records = []