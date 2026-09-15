"""Complete pattern: autonomous passenger generator.

The identifier is state, but the event timestamp is read when ``lambdaf()``
actually runs. Do not stamp a payload in ``deltint()`` with the current time
and then schedule that payload for a future event.
"""

import json
import numpy as np
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class PassengerGenerator(Atomic):
    """Emit a timestamped item and event at t=0 and then periodically forever, stamping each payload with the actual simulation time when it is emitted."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "passenger_generated"))
        self.passenger_num = 0

    def initialize(self):
        self.passenger_num = 0
        # Schedule lambdaf() at t=0.5 for initial passengers. 
        self.hold_in("GENERATE_INITIAL", 0.5)

    def deltext(self, e):
        # This source has no input ports. The method remains a valid no-op.
        return None

    def lambdaf(self):
        if self.phase.startswith("GENERATE"):
            emitted_at = get_current_time()
            station_id = int(self.phase.split("_")[-1])
            # Build the internal port payload and any public record independently.
            # Their field names may differ; neither schema is an alias for the other.
            passenger_id = self.passenger_num * 100 + station_id * 10
            destination = np.random.choice([i for i in range(1, 6) if i != station_id])
            passenger = {
                "passenger_id": passenger_id,
                "passenger_num": self.passenger_num,
                "origin": station_id,
                "destination": destination,
            }
            self.output["passenger_generated"].add(passenger)
            print(json.dumps({
                "time": emitted_at,
                "event": "passenger_generated",
                "entity_type": "passenger_generator",
                "station_id": station_id,
                "station": ["Bayview", "Carling", "Carleton", "Confed", "Greenboro"][station_id - 1],
                "payload": passenger,
            }), flush=True)

    def deltint(self):
        if self.phase.startswith("GENERATE"):
            self.passenger_num += 1
            interval = np.clip(np.random.normal(300, 300), 60, 540)  # Convert to seconds and round
            interval = round(interval)
            self.hold_in("GENERATE", interval)

    def exit(self):
        pass