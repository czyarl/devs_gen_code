#!/usr/bin/env python3
import argparse
import sys
import json
import logging
from typing import Any, Dict

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock


class SEIRDAtomic(Atomic):
    """
    Discrete-time (dt) SEIRD compartmental model as a DEVS atomic component.
    State updates occur at fixed time intervals, with a final truncated step
    to hit sim_end exactly.
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        *,
        mortality: float,
        infectivity_period: float,
        dt: float,
        incubation_period: float,
        total_population: int,
        initial_infective: int,
        transmission_rate: float,
        sim_end: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Ports (optional, but useful for connecting to a logger model if desired)
        self.add_out_port(Port(dict, "state"))

        # Parameters
        self.mortality = float(mortality)  # percent [0, 100]
        self.infectivity_period = float(infectivity_period)
        self.dt = float(dt)
        self.incubation_period = float(incubation_period)
        self.N = float(total_population)
        self.I0 = float(initial_infective)
        self.beta = float(transmission_rate)
        self.sim_end = float(sim_end)

        # State
        self.time = 0.0
        self.S = 0.0
        self.E = 0.0
        self.I = 0.0
        self.R = 0.0
        self.D = 0.0

        # Control
        self._last_step = 0.0
        self._pending_output: Dict[str, Any] | None = None

        # Schedule initialize() via DEVS lifecycle
        self.hold_in("INIT", 0.0)

    def initialize(self):
        self.time = 0.0
        self.S = max(self.N - self.I0, 0.0)
        self.E = 0.0
        self.I = max(self.I0, 0.0)
        self.R = 0.0
        self.D = 0.0

        # Prepare first step
        remaining = self.sim_end - self.time
        if remaining <= 0.0:
            self._last_step = 0.0
            self.hold_in("DONE", float("inf"))
        else:
            step = min(self.dt, remaining)
            self._last_step = step
            self.hold_in("RUN", step)

    def lambdaf(self):
        # Output only (no state modification)
        if self._pending_output is not None:
            self.output["state"].add(self._pending_output)

    def deltint(self):
        if self.phase != "RUN":
            # Stay passive when done
            self._pending_output = None
            self.hold_in("DONE", float("inf"))
            return

        step = float(self._last_step)
        if step <= 0.0:
            self._pending_output = None
            self.hold_in("DONE", float("inf"))
            return

        # Snapshot old values
        S_old = self.S
        E_old = self.E
        I_old = self.I
        R_old = self.R
        D_old = self.D

        # Flows (per specification)
        # S -> E
        if self.N > 0.0:
            new_exposed = (self.beta * S_old * I_old / self.N) * step
        else:
            new_exposed = 0.0
        new_exposed = min(new_exposed, S_old)

        # E -> I
        new_infective = (E_old / self.incubation_period) * step
        new_infective = min(new_infective, E_old)

        # I -> R / D
        mort_frac = max(0.0, min(1.0, self.mortality / 100.0))
        new_deceased = (I_old / self.infectivity_period) * mort_frac * step
        new_recovered = (I_old / self.infectivity_period) * (1.0 - mort_frac) * step

        # Update compartments
        S_new = S_old - new_exposed
        E_new = E_old + new_exposed - new_infective
        I_new = I_old + new_infective - new_deceased - new_recovered
        R_new = R_old + new_recovered
        D_new = D_old + new_deceased

        # Clamp tiny numerical drift
        S_new = max(S_new, 0.0)
        E_new = max(E_new, 0.0)
        I_new = max(I_new, 0.0)
        R_new = max(R_new, 0.0)
        D_new = max(D_new, 0.0)

        # Advance time
        self.time = self.time + step

        # Conservation tweak (within floating precision)
        total = S_new + E_new + I_new + R_new + D_new
        diff = self.N - total
        # Put any tiny diff into S (but don't allow negative)
        if abs(diff) > 1e-9:
            if S_new + diff >= 0.0:
                S_new += diff
            else:
                # If S would go negative, push as much as possible into S, remainder into E
                remainder = diff + S_new
                S_new = 0.0
                E_new = max(E_new + remainder, 0.0)

        self.S, self.E, self.I, self.R, self.D = S_new, E_new, I_new, R_new, D_new

        # Prepare optional output payload (not printed; only goes to out port)
        self._pending_output = {
            "time": float(self.time),
            "susceptible": float(self.S),
            "exposed": float(self.E),
            "infective": float(self.I),
            "recovered": float(self.R),
            "deceased": float(self.D),
        }

        # Schedule next step (truncate to hit sim_end exactly)
        remaining = self.sim_end - self.time
        if remaining <= 0.0:
            self._last_step = 0.0
            self.hold_in("DONE", float("inf"))
        else:
            next_step = min(self.dt, remaining)
            self._last_step = next_step
            self.hold_in("RUN", next_step)

    def deltext(self, e):
        # No external inputs expected; keep current schedule.
        # Must call hold_in at end of deltext by requirement.
        if self.phase == "DONE":
            self.hold_in("DONE", float("inf"))
        else:
            # Continue with remaining time to next internal event.
            # In xdevs, sigma is managed internally; simplest is to keep current phase with same sigma.
            # We do not alter state or reschedule due to no inputs.
            self.hold_in(self.phase, self.sigma)

    def exit(self):
        # No-op cleanup
        return


class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None, **config):
        super().__init__(name)
        self.parent = parent

        self.seird = SEIRDAtomic(name="seird", parent=self, **config)
        self.add_component(self.seird)
        # No couplings needed for final-output-in-main pattern.


def _validate_args(args: argparse.Namespace) -> None:
    if args.total_population < 0:
        raise ValueError("--total_population must be >= 0")
    if args.initial_infective < 0:
        raise ValueError("--initial_infective must be >= 0")
    if args.initial_infective > args.total_population:
        raise ValueError("--initial_infective must be <= --total_population")
    if args.dt <= 0:
        raise ValueError("--dt must be > 0")
    if args.incubation_period <= 0:
        raise ValueError("--incubation_period must be > 0")
    if args.infectivity_period <= 0:
        raise ValueError("--infectivity_period must be > 0")
    if not (0.0 <= args.mortality <= 100.0):
        raise ValueError("--mortality must be in [0, 100]")
    if args.transmission_rate < 0:
        raise ValueError("--transmission_rate must be >= 0")
    if args.simulation_time < 0:
        raise ValueError("--simulation_time must be >= 0")


def main() -> int:
    parser = argparse.ArgumentParser()
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

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        _validate_args(args)
    except Exception as exc:
        logging.error(str(exc))
        return 2

    config = dict(
        mortality=args.mortality,
        infectivity_period=args.infectivity_period,
        dt=args.dt,
        incubation_period=args.incubation_period,
        total_population=args.total_population,
        initial_infective=args.initial_infective,
        transmission_rate=args.transmission_rate,
        sim_end=args.simulation_time,
    )

    root = System(name="system", parent=None, **config)
    coord = Coordinator(root, clock=SimulationClock(0.0))

    coord.initialize()
    coord.simulate_time(float(args.simulation_time))

    m = root.seird

    out_obj = {
        "time": round(float(args.simulation_time), 2),
        "susceptible": round(float(m.S), 2),
        "exposed": round(float(m.E), 2),
        "infective": round(float(m.I), 2),
        "recovered": round(float(m.R), 2),
        "deceased": round(float(m.D), 2),
    }
    print(json.dumps(out_obj), file=sys.stdout, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())