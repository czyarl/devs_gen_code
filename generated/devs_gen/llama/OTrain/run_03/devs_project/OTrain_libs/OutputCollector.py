"""Complete pattern: external JSONL output owned by an atomic sink."""

import json
from xdevs.models import Atomic, Coupled, Port


class OutputCollector(Atomic):
    """Write only received business records to stdout as JSONL."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

    def initialize(self):
        self.passivate("WAITING")

    def deltext(self, e):
        # No external input ports
        pass

    def lambdaf(self):
        # No DEVS output ports
        pass

    def deltint(self):
        self.passivate("WAITING")

    def exit(self):
        # No external IO specified
        pass