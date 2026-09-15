"""SubnetB2: Delays incoming ACK packets by 3000 milliseconds and forwards them to the Server component."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class SubnetB2(Atomic):
    """Delays incoming ACK packets by a fixed amount and forwards them."""

    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "ack_out"))
        self.pending = []

    def initialize(self):
        self.pending = []
        self.passivate("IDLE")

    def _reschedule_from_pending(self) -> None:
        if not self.pending:
            self.passivate("IDLE")
            return
        now = get_current_time()
        next_time = min(delivery_time for delivery_time, _ in self.pending)
        self.hold_in("WAITING", max(0.0, next_time - now))

    def deltext(self, e):
        now = get_current_time()
        for item in self.input["ack_in"].values:
            payload = dict(item)
            self.pending.append((now + self.delay, payload))
        self._reschedule_from_pending()

    def lambdaf(self):
        if self.phase != "WAITING":
            return
        now = get_current_time()
        for delivery_time, payload in self.pending:
            if delivery_time <= now:
                self.output["ack_out"].add(dict(payload))

    def deltint(self):
        now = get_current_time()
        self.pending = [
            (delivery_time, payload)
            for delivery_time, payload in self.pending
            if delivery_time > now
        ]
        self._reschedule_from_pending()

    def exit(self):
        pass