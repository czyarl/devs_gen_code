import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class CustomerSource(Atomic):
    """Reads the entire event schedule from sys.stdin during initialization.
    
    Each line is expected in the format 'HH:MM:SS:mm EventName'. The timestamp is
    parsed and converted to absolute simulation seconds (HH * 3600 + MM * 60 + SS + mm / 1000).
    Events are stored internally in a list sorted by simulation time. The model schedules
    itself to trigger an internal transition at the timestamp of the first event. At each
    internal transition, it outputs the string 'newcust' via the 'cust' port and schedules
    the next event. After the last event is processed, the model enters a passive state
    (sigma = infinity). Lines that do not match the format or where EventName is not
    'newcust' are ignored.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Output port for customer events
        self.add_out_port(Port(str, "cust"))
        
        # Internal storage for parsed events
        self.events = []  # List of (time, event_name) tuples sorted by time

    def initialize(self):
        """Reads sys.stdin, parses events, and schedules the first one."""
        self.events = []
        
        # Read all lines from stdin
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
                
            parts = line.split()
            # Expected format: HH:MM:SS:mm EventName
            if len(parts) != 2:
                continue
                
            timestamp_str, event_name = parts
            
            # Filter for specific event name
            if event_name != "newcust":
                continue
                
            try:
                # Parse HH:MM:SS:mm
                time_parts = timestamp_str.split(":")
                if len(time_parts) != 4:
                    continue
                    
                hh = int(time_parts[0])
                mm = int(time_parts[1])
                ss = int(time_parts[2])
                ms = int(time_parts[3])
                
                # Convert to absolute simulation seconds
                total_seconds = hh * 3600 + mm * 60 + ss + (ms / 1000.0)
                
                self.events.append((total_seconds, event_name))
            except ValueError:
                # Ignore lines with malformed numbers
                continue
        
        # Sort events by time
        self.events.sort(key=lambda x: x[0])
        
        if self.events:
            # Schedule the first event
            first_event_time = self.events[0][0]
            self.hold_in("WAITING", first_event_time)
        else:
            # No events to process
            self.passivate("PASSIVE")

    def deltext(self, e: float):
        """This model has no input ports, so this is never called."""
        self.continuef(e)

    def lambdaf(self):
        """Outputs the 'newcust' string when an internal transition triggers."""
        if self.phase == "WAITING" and self.events:
            # The event at index 0 is the one currently being processed
            # We output the string "newcust" as required
            self.output["cust"].add("newcust")

    def deltint(self):
        """Advances to the next event or passivates if done."""
        if self.phase == "WAITING":
            # Remove the event that was just processed
            if self.events:
                self.events.pop(0)
            
            if self.events:
                # Schedule the next event
                # Calculate time difference from current simulation time
                # However, in xDEVS, sigma is relative to current time.
                # The events list contains absolute times.
                # We need to calculate the delay until the next event.
                
                current_time = get_current_time()
                next_event_time = self.events[0][0]
                
                delay = next_event_time - current_time
                
                # Ensure delay is not negative due to floating point or timing issues
                if delay < 0:
                    delay = 0.0
                    
                self.hold_in("WAITING", delay)
            else:
                # No more events
                self.passivate("PASSIVE")
        else:
            self.passivate("PASSIVE")

    def exit(self):
        """Cleanup."""
        pass