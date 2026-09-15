"""Complete pattern: external JSONL output owned by an atomic sink."""

import json
from xdevs.models import Atomic, Coupled, Port


class ReportCollector(Atomic):
    """Write only received business records to stdout as JSONL."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

    def initialize(self):
        self.passivate("WAITING")

    def deltext(self, e):
        # Read from stdin
        import sys
        for line in sys.stdin:
            try:
                event = json.loads(line)
                # This is OS-level external IO, not a DEVS port write. The target
                # specification determines the exact schema used in real code.
                print(json.dumps(event), flush=True)
            except json.JSONDecodeError:
                pass
        self.passivate("WAITING")

    def lambdaf(self):
        # A pure sink has no DEVS output ports.
        pass

    def deltint(self):
        self.passivate("WAITING")

    def exit(self):
        # Never print lifecycle or diagnostic records to stdout.
        pass