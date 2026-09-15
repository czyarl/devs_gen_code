import json
import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class Subnet(Atomic):
    """
    Atomic deterministic-loss, uni-directional channel with fixed latency.

    Receives dict messages on msg_in, deterministically decides drop/pass based on
    per-instance evolving noise state, emits one stdout JSONL KPI record per arrival,
    and when passing forwards the exact same dict unchanged after channel_delay.
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

        # Immutable configuration
        self.channel: str = channel
        self.channel_delay: float = float(channel_delay)

        # Noise state
        self.x_old: int = int(seed)

        # In-flight delivery state (single pending delivery)
        self.pending_msg: dict | None = None
        self.pending_deadline: float | None = None

        # Ports
        self.add_in_port(Port(dict, "msg_in"))
        self.add_out_port(Port(dict, "msg_out"))

        # Monotonic stdout time guard (best-effort)
        self._last_print_time: float = -float("inf")

    def initialize(self):
        # Reset runtime state; keep config as provided.
        # x_old already set from seed in __init__.
        self.pending_msg = None
        self.pending_deadline = None
        self._last_print_time = -float("inf")
        self.passivate("IDLE")

    def _emit_packet_get(self, t: float, behavior: str, noise_value: int):
        # Enforce nondecreasing timestamps for stdout records.
        if t < self._last_print_time:
            # Must not print decreasing times; clamp to last printed time.
            # This should not occur in correct simulations.
            t = self._last_print_time
        self._last_print_time = t

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

    def deltext(self, e: float):
        # Preserve remaining time if already delaying an in-flight message.
        if self.phase == "DELAYING":
            self.continuef(e)

        now = float(get_current_time())

        # Process each arrival in the bag (even though scenario expects one).
        for msg in self.input["msg_in"].values:
            # Update noise and decide fate for every arrival.
            x_new = (17 * int(self.x_old) + 11) % 100
            behavior = "drop" if x_new < 10 else "pass"
            self.x_old = int(x_new)

            # Emit KPI immediately at arrival time.
            self._emit_packet_get(now, behavior, x_new)

            if behavior == "drop":
                # Discard message; do not schedule output for it.
                continue

            # behavior == "pass"
            if self.pending_msg is not None:
                # Overlap: preserve previously scheduled delivery unchanged.
                # Conservatively drop the new arrival after emitting its KPI.
                continue

            # Store exact same dict object for later output (no mutation/copy).
            self.pending_msg = msg
            self.pending_deadline = now + self.channel_delay

            # Schedule delivery after fixed delay; allow zero-delay.
            self.hold_in("DELAYING", float(self.channel_delay))

        # If no pending delivery exists, ensure passivated.
        if self.pending_msg is None:
            self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "DELAYING" and self.pending_msg is not None:
            # Deliver the exact same message unchanged.
            self.output["msg_out"].add(self.pending_msg)

    def deltint(self):
        if self.phase == "DELAYING":
            # Clear pending delivery after output.
            self.pending_msg = None
            self.pending_deadline = None
        self.passivate("IDLE")

    def exit(self):
        # No special termination action required.
        pass