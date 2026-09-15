from xdevs.models import Atomic, Coupled, Port
import json
import sys


class HairCuttingPhase(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "cust"))
        self.add_out_port(Port(dict, "out"))
        self.in_flight = None

    def initialize(self):
        self.in_flight = None
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "CUTTING":
            self.continuef(e)
            return

        for item in self.input["cust"].values:
            self.in_flight = dict(item)
            self.hold_in("CUTTING", 20.0)
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "CUTTING" and self.in_flight is not None:
            self.output["out"].add(dict(self.in_flight))

    def deltint(self):
        self.in_flight = None
        self.passivate("IDLE")

    def exit(self):
        pass

def main():
    # Read from stdin
    simulation_time = 1000000.0
    hair_cutting_phase = HairCuttingPhase("hair_cutting-phase", None)
    hair_cutting_phase = hair_cutting_phase

    # Run the simulation
    # ...

if __name__ == "__main__":
    main()