import sys
import json

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class InputSource(Atomic):
    """
    Reads timestamped 'control' and 'request' commands from stdin.
    Sends control messages to Sender and request messages to Server.
    Writes JSONL records to stdout for 'control_cmd' and 'download_valve_change'.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Output Ports
        self.add_out_port(Port(int, "control_out"))
        self.add_out_port(Port(bool, "request_out"))
        
        # Internal state
        self.schedule = []  # List of tuples: (time_ms, type, value)
        self.next_index = 0
        self.simulated_time = 0.0
        
        # Temporary storage for the current event to be emitted
        self.current_event = None

    @staticmethod
    def _parse_timestamp_to_ms(text: str) -> float:
        """
        Parses HH:MM:SS or HH:MM:SS:mmm into milliseconds.
        """
        parts = text.split(":")
        if len(parts) not in (3, 4):
            raise ValueError(f"Invalid timestamp format: {text}")
        
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
        
        total_ms = (hours * 3600 + minutes * 60 + seconds) * 1000
        
        if len(parts) == 4:
            # Milliseconds part
            ms_str = parts[3]
            # Pad or truncate to 3 digits if necessary, though input spec implies mmm
            if len(ms_str) > 3:
                ms_str = ms_str[:3]
            elif len(ms_str) < 3:
                ms_str = ms_str.ljust(3, '0')
            total_ms += int(ms_str)
            
        return float(total_ms)

    def _read_schedule(self) -> None:
        """
        Reads all lines from stdin, parses them, and stores in self.schedule.
        Format: HH:MM:SS[:mmm] type value
        """
        parsed = []
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            
            fields = line.split()
            if len(fields) < 3:
                # Malformed line, skip
                continue
            
            try:
                time_ms = self._parse_timestamp_to_ms(fields[0])
                cmd_type = fields[1]
                value_str = fields[2]
                
                if cmd_type == 'control':
                    value = int(value_str)
                elif cmd_type == 'request':
                    if value_str == '1':
                        value = True
                    elif value_str == '0':
                        value = False
                    else:
                        raise ValueError(f"Invalid request value: {value_str}")
                else:
                    # Unknown type, skip
                    continue
                
                parsed.append((time_ms, cmd_type, value))
                
            except ValueError:
                # Skip lines with parsing errors
                continue
        
        # Sort by time
        self.schedule = sorted(parsed, key=lambda x: x[0])

    def initialize(self):
        self._read_schedule()
        self.next_index = 0
        self.simulated_time = 0.0
        
        if not self.schedule:
            self.passivate("DONE")
            return
        
        # Schedule the first event
        first_time = self.schedule[0][0]
        self.hold_in("WAITING", max(0.0, first_time))

    def deltext(self, e):
        # This model has no input ports, so this shouldn't be called in a valid simulation,
        # but we must implement it as per Atomic interface.
        self.continuef(e)

    def lambdaf(self):
        """
        Emit the DEVS output and write to stdout.
        """
        if self.phase == "EMIT":
            if self.current_event:
                time_ms, cmd_type, value = self.current_event
                
                if cmd_type == 'control':
                    # Send to Sender
                    self.output["control_out"].add(value)
                    
                    # Write JSONL to stdout
                    # Schema: {"model": "sender", "type": "control_cmd", "val": {"added": <int>}}
                    # Note: The locked contract specifies "value containing the added packet count".
                    record = {
                        "timestamp_ms": time_ms,
                        "model": "sender",
                        "type": "control_cmd",
                        "val": {"added": value}
                    }
                    print(json.dumps(record), flush=True)
                    
                elif cmd_type == 'request':
                    # Send to Server
                    self.output["request_out"].add(value)
                    
                    # Write JSONL to stdout
                    # Schema: {"model": "server_sender", "type": "download_valve_change", "val": {"allowed": <bool>}}
                    record = {
                        "timestamp_ms": time_ms,
                        "model": "server_sender",
                        "type": "download_valve_change",
                        "val": {"allowed": value}
                    }
                    print(json.dumps(record), flush=True)

    def deltint(self):
        if self.phase == "WAITING":
            # Time to process the next command
            # We transition to EMIT phase with sigma=0 to output immediately
            if self.next_index < len(self.schedule):
                self.current_event = self.schedule[self.next_index]
                self.next_index += 1
                self.hold_in("EMIT", 0.0)
            else:
                self.passivate("DONE")
                
        elif self.phase == "EMIT":
            # Output has been sent, schedule next wait
            if self.next_index < len(self.schedule):
                next_time = self.schedule[self.next_index][0]
                # Update simulated time tracking to calculate delta
                self.simulated_time += self.sigma
                
                delay = max(0.0, next_time - self.simulated_time)
                self.hold_in("WAITING", delay)
            else:
                self.passivate("DONE")

    def exit(self):
        pass