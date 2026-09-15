from xdevs.models import Atomic, Coupled, Port
from .AircraftCoordinator_libs.Aircraft import Aircraft

class AircraftCoordinator(Coupled):
    def __init__(self, name: str, parent: Coupled | None, num_aircraft: int, flight_time: float, unload_time: float, return_time: float, maintenance_time: float):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, name="assignment_created"))
        self.add_out_port(Port(dict, name="depart"))
        self.add_out_port(Port(dict, name="return"))
        self.add_out_port(Port(dict, name="maintenance_start"))
        self.add_out_port(Port(dict, name="maintenance_end"))

        self.aircrafts = []
        for i in range(num_aircraft):
            aircraft = Aircraft(name=f"aircraft_{i}", parent=self, aircraft_id=i, flight_time=flight_time, unload_time=unload_time, return_time=return_time, maintenance_time=maintenance_time)
            self.aircrafts.append(aircraft)
            self.add_component(aircraft)

            self.add_coupling(self.output["depart"], aircraft.input["assignment"])
            self.add_coupling(aircraft.output["depart"], self.input["assignment_created"])
            self.add_coupling(aircraft.output["return"], self.output["return"])
            self.add_coupling(aircraft.output["maintenance_start"], self.output["maintenance_start"])
            self.add_coupling(aircraft.output["maintenance_end"], self.output["maintenance_end"])