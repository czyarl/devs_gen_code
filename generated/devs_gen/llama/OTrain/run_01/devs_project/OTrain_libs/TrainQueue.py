"""TrainQueue atomic model implementation."""

import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class TrainQueue(Atomic):
    """Manages passengers on the train, handles their exit at specific destinations."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

    def initialize(self):
        self.passengers = {}
        self.passenger_num = 0
        self.hold_in("WAITING", 0.0)

    def deltext(self, e):
        if self.phase == "WAITING":
            self.continuef(e)
            return

    def lambdaf(self):
        if self.phase != "WAITING":
            return

    def deltint(self):
        pass

    def exit(self):
        pass