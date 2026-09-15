import json
import sys

from xdevs.models import Atomic, Coupled, Port


class InputReader(Atomic):
    """
    Atomic model acting as the simulation's entry point.
    Reads and parses external input data from stdin, schedules events,
    and outputs JSONL records to stdout and DEVS messages to the AAM.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Output port for DEVS communication
        self.add_out_port(Port(dict, "request_out"))
        
        # Internal storage for parsed events
        self.event_queue = []
        
        # State variables
        self.current_time = 0.0
        self.payload_buffer = None  # To store data for lambdaf

    @staticmethod
    def _parse_timestamp(ts_str: str) -> float:
        """Converts HH:MM:SS:mmm string to float seconds."""
        parts = ts_str.split(":")
        if len(parts) != 4:
            raise ValueError(f"Invalid timestamp format: {ts_str}")
        
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
        milliseconds = int(parts[3])
        
        return hours * 3600.0 + minutes * 60.0 + seconds + (milliseconds / 1000.0)

    def _read_input(self) -> None:
        """Reads all lines from stdin and parses them into the event queue."""
        self.event_queue = []
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            
            parts = line.split()
            if len(parts) < 3:
                continue
            
            try:
                ts = self._parse_timestamp(parts[0])
                valid = int(parts[1])
                invalid = int(parts[2])
                
                self.event_queue.append((ts, valid, invalid))
            except ValueError:
                continue
        
        self.event_queue.sort(key=lambda x: x[0])

    def initialize(self):
        """Initializes the model, reads input, and schedules the first event."""
        self._read_input()
        self.current_time = 0.0
        self.hold_in("START", 0.0)

    def deltext(self, e: float):
        """This model has no input ports."""
        self.continuef(e)

    def lambdaf(self):
        """Outputs DEVS messages and external IO (stdout) based on the current phase."""
        if self.phase == "START":
            record = {
                "time": 0.0,
                "model": "input_reader1",
                "event": "start",
                "data": {}
            }
            print(json.dumps(record), flush=True)
            
        elif self.phase == "INPUT":
            if self.payload_buffer:
                valid, invalid = self.payload_buffer
                record = {
                    "time": self.current_time,
                    "model": "input_reader1",
                    "event": "input",
                    "data": {
                        "valid": valid,
                        "invalid": invalid
                    }
                }
                print(json.dumps(record), flush=True)
                
                self.output["request_out"].add({
                    "valid": valid,
                    "invalid": invalid
                })

    def deltint(self):
        """Internal transition logic."""
        if self.phase == "START":
            if self.event_queue:
                next_ts = self.event_queue[0][0]
                if next_ts == 0.0:
                    self.current_time = 0.0
                    _, valid, invalid = self.event_queue.pop(0)
                    self.payload_buffer = (valid, invalid)
                    self.hold_in("INPUT", 0.0)
                else:
                    self.current_time = 0.0
                    self.hold_in("WAITING", next_ts)
            else:
                self.passivate("PASSIVE")

        elif self.phase == "WAITING":
            if self.event_queue:
                ts, valid, invalid = self.event_queue.pop(0)
                self.current_time = ts
                self.payload_buffer = (valid, invalid)
                self.hold_in("INPUT", 0.0)
            else:
                self.passivate("PASSIVE")

        elif self.phase == "INPUT":
            if self.event_queue:
                next_ts = self.event_queue[0][0]
                self.hold_in("WAITING", next_ts - self.current_time)
            else:
                self.passivate("PASSIVE")

    def exit(self):
        pass