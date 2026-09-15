import sys
import json

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Subnet(Atomic):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        channel: str,
        seed: int,
        channel_delay: float,
    ):
        super().__init__(name)
        self.parent = parent

        if channel not in ("forward", "backward"):
            print(
                f"Subnet channel must be 'forward' or 'backward', got: {channel!r}",
                file=sys.stderr,
                flush=True,
            )
            raise ValueError("Invalid channel label")

        if channel_delay < 0:
            print(
                f"Subnet channel_delay must be >= 0, got: {channel_delay!r}",
                file=sys.stderr,
                flush=True,
            )
            raise ValueError("Invalid channel_delay")

        self.channel = channel
        self.channel_delay = float(channel_delay)

        self.add_in_port(Port(dict, "in_pkt"))
        self.add_out_port(Port(dict, "out_pkt"))

        self.x_old: int = int(seed) % 100
        # pending deliveries as list of (delivery_time: float, payload: dict)
        self._pending: list[tuple[float, dict]] = []

    def initialize(self):
        self._pending = []
        self.passivate("IDLE")

    def _emit_packet_get(self, t: float, behavior: str, noise_value: int) -> None:
        record = {
            "time": float(f"{t:.2f}"),
            "entity": "subnet",
            "event": "packet_get",
            "payload": {
                "behavior": behavior,
                "channel": self.channel,
                "noise_value": int(noise_value),
            },
        }
        print(json.dumps(record), flush=True)

    def _reschedule_from_pending(self) -> None:
        if not self._pending:
            self.passivate("IDLE")
            return
        now = get_current_time()
        next_time = min(delivery_time for delivery_time, _ in self._pending)
        self.hold_in("DELIVERING", max(0.0, next_time - now))

    def deltext(self, e: float):
        now = get_current_time()

        # Process each arrival deterministically in the order provided by the bag iterator.
        for unit in self.input["in_pkt"].values:
            x_new = (17 * self.x_old + 11) % 100
            behavior = "drop" if x_new < 10 else "pass"
            self.x_old = x_new

            # Emit KPI immediately at arrival time (before any transmission delay).
            self._emit_packet_get(now, behavior, x_new)

            if behavior == "pass":
                payload = dict(unit)
                self._pending.append((now + self.channel_delay, payload))

        self._reschedule_from_pending()

    def lambdaf(self):
        if self.phase != "DELIVERING":
            return
        now = get_current_time()
        # Emit all deliveries due at or before now.
        for delivery_time, payload in self._pending:
            if delivery_time <= now:
                self.output["out_pkt"].add(dict(payload))

    def deltint(self):
        now = get_current_time()
        # Remove delivered items.
        self._pending = [
            (delivery_time, payload)
            for delivery_time, payload in self._pending
            if delivery_time > now
        ]
        self._reschedule_from_pending()

    def exit(self):
        pass