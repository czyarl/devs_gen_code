"""Atomic DEVS model for the LoadingQueue component."""

import json
from collections import deque
from typing import Deque, Dict, Set

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class LoadingQueue(Atomic):
    """Retain FIFO pallets and any expiration timers. On a claim containing a selected aircraft_id, 
    atomically remove one eligible item and return both IDs; independently write queue and expiration records to stdout."""

    def __init__(self, name: str, parent: Coupled | None, pallet_expiration_time: float):
        super().__init__(name)
        self.parent = parent
        self.pallet_expiration_time = pallet_expiration_time
        self.add_in_port(Port(dict, "pallet_in"))
        self.add_in_port(Port(dict, "claim_in"))
        self.add_out_port(Port(dict, "claimed_out"))
        self.queue: Deque[Dict] = deque()
        self.expiration_times: Dict[int, float] = {}
        self.total_expired = 0
        self.next_pallet_id = 1

    def initialize(self):
        self.queue = deque()
        self.expiration_times = {}
        self.total_expired = 0
        self.next_pallet_id = 1
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "OUTPUT_READY":
            self.continuef(e)
            return

        # Process incoming pallets
        for pallet in self.input["pallet_in"].values:
            pallet_id = pallet["pallet_id"]
            expiration_time = pallet["expiration_time"]
            self.queue.append({
                "pallet_id": pallet_id,
                "generation_time": expiration_time - self.pallet_expiration_time
            })
            self.expiration_times[pallet_id] = expiration_time
            # Emit pallet_queued event
            record = {
                "time": get_current_time(),
                "entity": "queue",
                "event": "pallet_queued",
                "payload": {
                    "pallet_id": pallet_id,
                    "queue_size": len(self.queue)
                }
            }
            print(json.dumps(record), flush=True)

        # Process claims
        for claim in self.input["claim_in"].values:
            aircraft_id = claim["aircraft_id"]
            # Check for expired pallets before processing claim
            self._check_and_expire_pallets()
            if self.queue:
                # Select oldest eligible pallet (FIFO)
                pallet = self.queue.popleft()
                pallet_id = pallet["pallet_id"]
                generation_time = pallet["generation_time"]
                # Remove from expiration tracking
                del self.expiration_times[pallet_id]
                # Prepare output
                output_payload = {
                    "aircraft_id": aircraft_id,
                    "pallet_id": pallet_id,
                    "generation_time": generation_time
                }
                self.output["claimed_out"].add(output_payload)
                self.hold_in("OUTPUT_READY", 0.0)
            else:
                # No pallets available, remain idle
                self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "OUTPUT_READY":
            # Output is already handled in deltext
            pass

    def deltint(self):
        # Check for expired pallets
        self._check_and_expire_pallets()
        if self.queue:
            # There are pallets in the queue, remain active
            self.hold_in("IDLE", 0.0)
        else:
            self.passivate("IDLE")

    def _check_and_expire_pallets(self):
        current_time = get_current_time()
        expired_pallets = []
        # Check for expired pallets
        for pallet_id, expiration_time in list(self.expiration_times.items()):
            if current_time >= expiration_time:
                expired_pallets.append(pallet_id)
        # Remove expired pallets
        for pallet_id in expired_pallets:
            # Remove from queue
            self.queue = deque([p for p in self.queue if p["pallet_id"] != pallet_id])
            # Remove from expiration tracking
            del self.expiration_times[pallet_id]
            # Increment total expired
            self.total_expired += 1
            # Emit pallet_expired event
            record = {
                "time": current_time,
                "entity": "queue",
                "event": "pallet_expired",
                "payload": {
                    "pallet_id": pallet_id,
                    "total_expired": self.total_expired
                }
            }
            print(json.dumps(record), flush=True)

    def exit(self):
        pass