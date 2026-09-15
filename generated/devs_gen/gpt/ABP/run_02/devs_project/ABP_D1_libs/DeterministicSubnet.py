import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class DeterministicSubnet(Atomic):
    """
    Atomic DEVS model: deterministic loss + fixed latency uni-directional channel.

    - On each pkt_in arrival: update noise state, decide drop/pass, log packet_get to stdout.
    - If pass: deliver the same dict on pkt_out after channel_delay (ms).
    - Supports multiple in-flight packets with independent due times.
    """

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

        # Locked init args
        self.channel = channel
        self.seed = seed
        self.channel_delay = float(channel_delay)

        # Ports (locked)
        self.add_in_port(Port(dict, "pkt_in"))
        self.add_out_port(Port(dict, "pkt_out"))

        # State
        self.x_old: int = int(seed)
        self.pending: list[tuple[float, dict]] = []

    def initialize(self):
        self.x_old = int(self.seed)
        self.pending = []
        self.passivate("IDLE")

    def _log_packet_get(self, now: float, behavior: str, noise_value: int) -> None:
        # time must be float with at least 2 decimals
        record = {
            "time": float(f"{now:.2f}"),
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
        if not self.pending:
            self.passivate("IDLE")
            return
        now = get_current_time()
        next_due = min(due for due, _ in self.pending)
        self.hold_in("WAITING", max(0.0, next_due - now))

    def deltext(self, e: float):
        now = get_current_time()

        # Process every arrival in the message bag deterministically in simulator-provided order.
        for pkt in self.input["pkt_in"].values:
            # Deterministic noise update and fate determination (immediate at arrival time)
            x_new = (17 * int(self.x_old) + 11) % 100
            behavior = "drop" if x_new < 10 else "pass"
            self.x_old = int(x_new)

            # Log at arrival time (before any channel_delay)
            self._log_packet_get(now, behavior, x_new)

            # If pass, schedule delivery after channel_delay; payload forwarded unchanged (dict)
            if behavior == "pass":
                try:
                    payload = dict(pkt)
                except Exception:
                    # Contract says treat as dict; if not, forward as-is but keep type safety.
                    payload = pkt
                self.pending.append((now + self.channel_delay, payload))

        self._reschedule_from_pending()

    def lambdaf(self):
        if self.phase != "WAITING":
            return

        now = get_current_time()
        # Emit all deliveries due at or before now.
        for due, payload in self.pending:
            if due <= now:
                self.output["pkt_out"].add(dict(payload))

    def deltint(self):
        now = get_current_time()
        # Remove delivered items
        self.pending = [(due, payload) for due, payload in self.pending if due > now]
        self._reschedule_from_pending()

    def exit(self):
        # No required termination behavior.
        pass