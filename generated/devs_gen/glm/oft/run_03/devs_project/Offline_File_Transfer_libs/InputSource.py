"""InputSource: Atomic DEVS model reading timestamped commands from stdin."""

import sys
import json

from xdevs.models import Atomic, Coupled, Port


class InputSource(Atomic):
    """Read timestamped commands from stdin and forward them to the system."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Output Ports
        self.control_out = Port(dict, "control_out")
        self.request_out = Port(dict, "request_out")
        self.add_out_port(self.control_out)
        self.add_out_port(self.request_out)

        # Internal State
        self.schedule = []  # List of (time_ms, type, value)
        self.next_index = 0
        self.current_time = 0.0

    @staticmethod
    def _parse_timestamp(text: str) -> float:
        """Parse HH:MM:SS[:mmm] to milliseconds."""
        parts = text.split(":")
        if len(parts) not in (3, 4):
            raise ValueError(f"Invalid timestamp format: {text}")
        
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
        millis = 0.0
        
        if len(parts) == 4:
            # Handle milliseconds (e.g., 000, 500)
            frac_str = parts[3]
            # Pad or truncate to 3 digits to handle cases like '1' or '12' if necessary,
            # though spec implies 'mmm'. Assuming standard 3-digit ms.
            if len(frac_str) <= 3:
                frac_str = frac_str.ljust(3, '0')
            millis = float(frac_str)
            
        return (hours * 3600.0 + minutes * 60.0 + seconds) * 1000.0 + millis

    def _read_stdin(self):
        """Read all lines from stdin and parse them into the schedule."""
        self.schedule = []
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            
            parts = line.split()
            if len(parts) < 3:
                # Format: HH:MM:SS[:mmm] type value
                # Need at least 3 parts: timestamp, type, value
                continue
            
            try:
                ts_str = parts[0]
                cmd_type = parts[1]
                value_str = parts[2]
                
                ts_ms = self._parse_timestamp(ts_str)
                
                # Validate type
                if cmd_type not in ("control", "request"):
                    continue
                
                # Validate value (integer)
                value = int(value_str)
                
                self.schedule.append((ts_ms, cmd_type, value))
                
            except (ValueError, IndexError):
                # Skip malformed lines silently or log to stderr
                # print(f"Skipping malformed line: {line}", file=sys.stderr)
                continue
        
        # Sort by timestamp to ensure chronological processing
        self.schedule.sort(key=lambda x: x[0])

    def initialize(self):
        """Read stdin and schedule the first event."""
        self._read_stdin()
        self.next_index = 0
        self.current_time = 0.0
        
        if not self.schedule:
            self.passivate("DONE")
        else:
            # Schedule the first event relative to time 0
            first_event_time = self.schedule[0][0]
            self.hold_in("ACTIVE", max(0.0, first_event_time))

    def deltext(self, e: float):
        """External transition: not used as this model has no input ports."""
        self.continuef(e)

    def lambdaf(self):
        """Output function: emit the command to the appropriate port."""
        if self.phase == "ACTIVE" and self.next_index < len(self.schedule):
            _, cmd_type, value = self.schedule[self.next_index]
            
            if cmd_type == "control":
                # Structure: {'added': int, 'total_remaining': int}
                # Note: 'total_remaining' is tracked by the Sender. 
                # InputSource just forwards the added amount.
                # However, the contract says the structure is {'added': int, 'total_remaining': int}.
                # Since InputSource doesn't know the total remaining, it sends what it knows.
                # Wait, looking at the contract: "structure": "{'added': int, 'total_remaining': int}"
                # And the requirement: "When control <N> is received: Update total_packets_to_send += N."
                # The InputSource generates the event. The Sender receives it.
                # Usually, the source sends just the delta. The structure in the contract might be 
                # what the *Sender* expects or what the *Source* emits.
                # Let's look at the "Relevant Requirements" -> R011.
                # "payload": "control <N>"
                # Let's look at "Stdout JSON Schema" -> "val": {"added": <int>, "total_remaining": <int>}
                # This stdout schema is for the *Sender* emitting a log event.
                # The Locked Contract for InputSource says:
                # "structure": "{'added': int, 'total_remaining': int}"
                # This is tricky. InputSource doesn't know total_remaining.
                # However, if I look at the reference implementation `stdin_plaintext_timestamped_event_source.py`,
                # it just emits what it parses.
                # Let's re-read the contract carefully.
                # "Parse 'control' commands and forward them to the Sender."
                # "structure": "{'added': int, 'total_remaining': int}"
                # If I must emit this structure, but I don't have total_remaining, I might have to assume 0 or -1?
                # Or maybe the contract implies the *Sender* updates it?
                # Actually, usually in these tasks, the "structure" field describes the payload on the wire.
                # If InputSource sends it, it must populate it.
                # Let's look at the sibling `Sender` input port: "structure": "{'added': int, 'total_remaining': int}"
                # Wait, Sender input port structure matches this.
                # But Sender logic is "Update total_packets_to_send += N".
                # If InputSource sends `total_remaining`, it's guessing.
                # Let's check the "Independent Boundary Effects" section.
                # "Recover the exact line format... from the original requirements."
                # Original requirements: "control <N>"
                # It seems `total_remaining` is an output of the Sender logic, not an input from Source.
                # However, the Locked Contract for `InputSource` explicitly says:
                # `control_out` structure: `{'added': int, 'total_remaining': int}`.
                # This is a contradiction with standard logic (Source shouldn't know state).
                # BUT, I must follow the Locked Interface.
                # If I must send `total_remaining`, what value do I send?
                # Maybe the contract implies that the *value* from stdin is the total? 
                # No, R011 says "Update total_packets_to_send += N". It's a delta.
                # Let's look at the `Sender` input port definition in the Context Info:
                # `control_in`: `{'added': int, 'total_remaining': int}`.
                # If the Sender expects this, maybe it ignores `total_remaining` from input?
                # Or maybe the InputSource is supposed to act as if it knows?
                # Let's assume `total_remaining` is 0 or None in the payload from InputSource, 
                # or perhaps the value itself if it meant "set total to N"?
                # "When control <N> is received: Update total_packets_to_send += N." -> Delta.
                # If I send `{'added': N, 'total_remaining': 0}`, the Sender can use `added`.
                # Let's check if there's any other interpretation.
                # If I look at the `Sender` logic description: "Update total_packets_to_send += N".
                # This suggests it only needs `added`.
                # I will populate `added` with the parsed value. 
                # For `total_remaining`, since I don't know it, and the contract forces the structure, 
                # I will set it to 0 or -1, or perhaps the value itself if it meant "set total to N"?
                # "Update ... += N" strongly implies delta.
                # I will send `added=N` and `total_remaining=0` (or None, but type is int).
                # Let's check the `Sender` implementation if I could... I can't.
                # I will assume `total_remaining` is ignored by the Sender or I provide a dummy value (0).
                # Actually, looking at the JSON schema for stdout: `{"model": "sender", "type": "control_cmd", "val": {"added": <int>, "total_remaining": <int>}}`.
                # This is the log event. The input port structure is likely copied from the log event structure in the prompt generation or vice versa.
                # I will send `{'added': value, 'total_remaining': 0}`. The Sender will likely use `added`.
                
                self.control_out.add({'added': value, 'total_remaining': 0})
                
            elif cmd_type == "request":
                # Structure: {'allowed': bool}
                # Value is 0 or 1.
                allowed = (value == 1)
                self.request_out.add({'allowed': allowed})

    def deltint(self):
        """Internal transition: advance to the next event."""
        self.current_time += self.sigma
        self.next_index += 1
        
        if self.next_index >= len(self.schedule):
            self.passivate("DONE")
        else:
            next_event_time = self.schedule[self.next_index][0]
            delay = next_event_time - self.current_time
            self.hold_in("ACTIVE", max(0.0, delay))

    def exit(self):
        pass