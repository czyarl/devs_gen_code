import json

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class RoomModel(Atomic):
    """
    Maintains the room's thermal state and heater control logic.
    Updates state on each external transition (outdoor temperature input)
    and writes a JSONL observation to stdout.
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        initial_room_temp: float,
        target_temp: float,
        heater_gain: float,
        loss_rate: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Constants from arguments
        self.initial_room_temp = initial_room_temp
        self.target_temp = target_temp
        self.heater_gain = heater_gain
        self.loss_rate = loss_rate

        # State variables
        self.room_temp = self.initial_room_temp
        self.control_signal = 0

        # Input port
        self.add_in_port(Port(float, "outdoor_temp_in"))

    def initialize(self):
        # Initialize state
        self.room_temp = self.initial_room_temp
        self.control_signal = 0
        # Wait for external input (outdoor temperature)
        self.passivate("WAITING")

    def deltext(self, e: float):
        """
        Process incoming outdoor temperature.
        Update room temperature, control signal, and write observation.
        """
        # Iterate over all received values (though contract implies one per step)
        for outdoor_temp in self.input["outdoor_temp_in"].values:
            # 1) Determine effective_outdoor_temp
            # Minimum of received value and current room_temp
            effective_outdoor_temp = min(float(outdoor_temp), self.room_temp)

            # 2) Compute heat_loss_temp_c
            # Reduce room_temp by 10% (loss_rate) of the difference
            # Mathematically: room_temp - (loss_rate * (room_temp - effective_outdoor_temp))
            diff = self.room_temp - effective_outdoor_temp
            heat_loss_temp_c = self.room_temp - (self.loss_rate * diff)

            # 3) Compute heater_output_c
            # heater_gain if previous control_signal was 1, else 0.0
            heater_output_c = self.heater_gain if self.control_signal == 1 else 0.0

            # 4) Compute new room_temp
            new_room_temp = heat_loss_temp_c + heater_output_c

            # 5) Determine new control_signal
            # 1 if new room_temp < target_temp, else 0
            new_control_signal = 1 if new_room_temp < self.target_temp else 0

            # Update internal state
            self.room_temp = new_room_temp
            self.control_signal = new_control_signal

            # Write JSONL record to stdout
            # Schema: {'time_sec': int, 'room_temp_c': float, 'heat_loss_temp_c': float, 'control_signal': int, 'heater_output_c': float}
            record = {
                "time_sec": int(get_current_time()),
                "room_temp_c": self.room_temp,
                "heat_loss_temp_c": heat_loss_temp_c,
                "control_signal": self.control_signal,
                "heater_output_c": heater_output_c,
            }
            print(json.dumps(record), flush=True)

        # After processing, passivate and wait for next input
        self.passivate("WAITING")

    def lambdaf(self):
        # No DEVS output ports defined for this model
        pass

    def deltint(self):
        # Internal transitions are not the primary driver here;
        # logic is driven by external inputs.
        # If we ever reach here (e.g. if we scheduled an internal event),
        # we should passivate.
        self.passivate("WAITING")

    def exit(self):
        # No cleanup required
        pass