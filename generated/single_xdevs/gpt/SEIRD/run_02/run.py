#!/usr/bin/env python3
import argparse
import sys
import json
import logging
from typing import Optional

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock


EPS = 1e-12


class SEIRDAtomic(Atomic):
    """
    Discrete-time SEIRD compartmental model using fixed/variable dt stepping.
    No inputs required. State is updated via internal transitions.
    """

    def __init__(
        self,
        name: str,
        parent: Optional[Coupled],
        *,
        mortality: float,
        infectivity_period: float,
        incubation_period: float,
        transmission_rate: float,
        dt: float,
        total_population: int,
        initial_infective: int,
        simulation_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Optional (unused) output port for potential coupling/inspection
        self.add_out_port(Port(dict, "state"))

        # Parameters
        self.mortality = float(mortality)
        self.infectivity_period = float(infectivity_period)
        self.incubation_period = float(incubation_period)
        self.beta = float(transmission_rate)
        self.dt = float(dt)
        self.N = float(total_population)
        self.I0 = float(initial_infective)
        self.simulation_time = float(simulation_time)

        # State variables
        self.S = 0.0
        self.E = 0.0
        self.I = 0.0
        self.R = 0.0
        self.D = 0.0

        # Time tracking
        self.elapsed_time = 0.0

        # Phase scheduling (actual scheduling done in initialize)
        self.hold_in("IDLE", 0.0)

    def initialize(self):
        self.elapsed_time = 0.0

        self.S = max(0.0, self.N - self.I0)
        self.E = 0.0
        self.I = max(0.0, self.I0)
        self.R = 0.0
        self.D = 0.0

        if self.simulation_time <= EPS:
            self.hold_in("DONE", float("inf"))
            return

        sigma = min(self.dt, max(0.0, self.simulation_time - self.elapsed_time))
        if sigma <= EPS:
            self.hold_in("DONE", float("inf"))
        else:
            self.hold_in("RUN", sigma)

    def lambdaf(self):
        # No outputs required for this task. Keep pure.
        return

    def deltint(self):
        if self.phase != "RUN":
            self.hold_in("DONE", float("inf"))
            return

        dt_step = float(self.sigma)
        if dt_step <= EPS:
            # Avoid infinite loop
            self.hold_in("DONE", float("inf"))
            return

        # Old state snapshot
        S_old = self.S
        E_old = self.E
        I_old = self.I
        R_old = self.R
        D_old = self.D
        N = self.N if self.N > 0.0 else (S_old + E_old + I_old + R_old + D_old)

        # Compute flows
        new_exposed = 0.0
        if N > 0.0:
            new_exposed = (self.beta * S_old * I_old / N) * dt_step
        new_exposed = min(new_exposed, S_old)
        if new_exposed < 0.0:
            new_exposed = 0.0

        new_infective = 0.0
        if self.incubation_period > 0.0:
            new_infective = (E_old / self.incubation_period) * dt_step
        new_infective = min(new_infective, E_old)
        if new_infective < 0.0:
            new_infective = 0.0

        mort_frac = max(0.0, min(1.0, self.mortality / 100.0))

        new_deceased = 0.0
        new_recovered = 0.0
        if self.infectivity_period > 0.0:
            new_deceased = (I_old / self.infectivity_period) * mort_frac * dt_step
            new_recovered = (I_old / self.infectivity_period) * (1.0 - mort_frac) * dt_step

        # Prevent over-drawing from I_old due to numerical issues
        total_out_I = new_deceased + new_recovered
        if total_out_I > I_old and total_out_I > 0.0:
            scale = I_old / total_out_I
            new_deceased *= scale
            new_recovered *= scale

        # Update compartments
        S_new = S_old - new_exposed
        E_new = E_old + new_exposed - new_infective
        I_new = I_old + new_infective - new_deceased - new_recovered
        R_new = R_old + new_recovered
        D_new = D_old + new_deceased

        # Clamp tiny negatives due to floating point
        self.S = 0.0 if S_new < 0.0 and abs(S_new) < 1e-9 else S_new
        self.E = 0.0 if E_new < 0.0 and abs(E_new) < 1e-9 else E_new
        self.I = 0.0 if I_new < 0.0 and abs(I_new) < 1e-9 else I_new
        self.R = 0.0 if R_new < 0.0 and abs(R_new) < 1e-9 else R_new
        self.D = 0.0 if D_new < 0.0 and abs(D_new) < 1e-9 else D_new

        # Advance time
        self.elapsed_time += dt_step

        # Schedule next step or finish
        remaining = self.simulation_time - self.elapsed_time
        if remaining <= EPS:
            self.elapsed_time = self.simulation_time
            self.hold_in("DONE", float("inf"))
        else:
            sigma = min(self.dt, remaining)
            if sigma <= EPS:
                self.elapsed_time = self.simulation_time
                self.hold_in("DONE", float("inf"))
            else:
                self.hold_in("RUN", sigma)

    def deltext(self, e):
        # No external inputs in this scenario; ignore.
        # Keep current phase/schedule.
        self.hold_in(self.phase, self.sigma)

    def exit(self):
        # No side effects; final output is produced in main().
        return


class System(Coupled):
    def __init__(self, name: str, parent: Optional[Coupled], **config):
        super().__init__(name)
        self.parent = parent

        self.seird = SEIRDAtomic(name="seird", parent=self, **config)
        self.add_component(self.seird)


def _validate_args(args: argparse.Namespace) -> None:
    if args.total_population < 0:
        raise SystemExit("--total_population must be >= 0")
    if args.initial_infective < 0:
        raise SystemExit("--initial_infective must be >= 0")
    if args.initial_infective > args.total_population:
        raise SystemExit("--initial_infective must be <= --total_population")
    if not (0.0 <= args.mortality <= 100.0):
        raise SystemExit("--mortality must be between 0 and 100")
    if args.dt <= 0.0:
        raise SystemExit("--dt must be > 0")
    if args.simulation_time < 0.0:
        raise SystemExit("--simulation_time must be >= 0")
    if args.infectivity_period <= 0.0:
        raise SystemExit("--infectivity_period must be > 0")
    if args.incubation_period <= 0.0:
        raise SystemExit("--incubation_period must be > 0")
    if args.transmission_rate < 0.0:
        raise SystemExit("--transmission_rate must be >= 0")


def main():
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="SEIRD simulation using xdevs.py (DEVS).")
    parser.add_argument("--test_name", type=str, required=True)
    parser.add_argument("--mortality", type=float, default=10.0)
    parser.add_argument("--infectivity_period", type=float, default=14.0)
    parser.add_argument("--dt", type=float, default=0.1)
    parser.add_argument("--incubation_period", type=float, default=5.0)
    parser.add_argument("--total_population", type=int, default=1000)
    parser.add_argument("--initial_infective", type=int, default=10)
    parser.add_argument("--transmission_rate", type=float, default=2.5)
    parser.add_argument("--simulation_time", type=float, default=10.0)

    args = parser.parse_args()
    _validate_args(args)

    root = System(
        name="system",
        parent=None,
        mortality=args.mortality,
        infectivity_period=args.infectivity_period,
        incubation_period=args.incubation_period,
        transmission_rate=args.transmission_rate,
        dt=args.dt,
        total_population=args.total_population,
        initial_infective=args.initial_infective,
        simulation_time=args.simulation_time,
    )

    coord = Coordinator(root, clock=SimulationClock(0.0))
    coord.initialize()
    coord.simulate_time(float(args.simulation_time))

    m = root.seird
    out = {
        "time": round(float(m.elapsed_time), 2),
        "susceptible": round(float(m.S), 2),
        "exposed": round(float(m.E), 2),
        "infective": round(float(m.I), 2),
        "recovered": round(float(m.R), 2),
        "deceased": round(float(m.D), 2),
    }
    print(json.dumps(out), file=sys.stdout, flush=True)


if __name__ == "__main__":
    main()