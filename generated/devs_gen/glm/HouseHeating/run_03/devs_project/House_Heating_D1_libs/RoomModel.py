import json

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class RoomModel(Atomic):
    """
    Atomic DEVS model for a single heated room with bang-bang heater control.
    Receives outdoor temperature, updates room physics, and writes observation JSONL.
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        target_temp: float,
        heater_gain_rate: float,
        heat_loss_rate: float,
        initial_room_temp: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Configuration parameters
        self.target_temp = target_temp
        self.heater_gain_rate = heater_gain_rate
        self.heat_loss_rate = heat_loss_rate

        # State variables
        self.room_temp = initial_room_temp
        self.control_signal = 0  # Initial control signal is 0 per R017

        # Observable intermediate values
        self.heat_loss_temp = initial_room_temp
        self.heater_output = 0.0

        # Ports
        self.add_in_port(Port(float, "outdoor_temp_in"))

    def initialize(self):
        # Initial state is set in __init__. We start passive and wait for the first input at t=1.
        # The simulation clock starts at 0. The first input arrives at t=1.
        self.passivate("WAITING")

    def deltext(self, e: float):
        # Process the incoming outdoor temperature for the current second.
        # The input protocol says "Receive one float value ... at every observation time."
        # We assume one value per bag.
        
        outdoor_temp = None
        for val in self.input["outdoor_temp_in"].values:
            outdoor_temp = float(val)
        
        if outdoor_temp is None:
            # Should not happen given the protocol, but handle gracefully
            self.passivate("WAITING")
            return

        # Physics update based on requirements
        # R021/R023: Cap outdoor temp to current room temp
        effective_outdoor_temp = min(outdoor_temp, self.room_temp)

        # R024: Calculate heat loss (10% of gap)
        gap = self.room_temp - effective_outdoor_temp
        loss = self.heat_loss_rate * gap
        
        # R025: Value after loss
        self.heat_loss_temp = self.room_temp - loss

        # R026: Heater gain based on previous control signal
        self.heater_output = self.heater_gain_rate if self.control_signal == 1 else 0.0

        # R027: New room temperature
        self.room_temp = self.heat_loss_temp + self.heater_output

        # R029: Update control signal for next step
        self.control_signal = 1 if self.room_temp < self.target_temp else 0

        # External IO: Write JSONL record
        # R016/R035: Schema requirements
        record = {
            "time_sec": int(get_current_time()),
            "room_temp_c": self.room_temp,
            "heat_loss_temp_c": self.heat_loss_temp,
            "control_signal": self.control_signal,
            "heater_output_c": self.heater_output,
        }
        print(json.dumps(record), flush=True)

        # Wait for next input
        self.passivate("WAITING")

    def lambdaf(self):
        # No DEVS output ports defined for this model
        pass

    def deltint(self):
        # Internal transitions are not used as this model is driven by external input
        # at discrete time steps.
        self.passivate("WAITING")

    def exit(self):
        # No specific cleanup required
        pass