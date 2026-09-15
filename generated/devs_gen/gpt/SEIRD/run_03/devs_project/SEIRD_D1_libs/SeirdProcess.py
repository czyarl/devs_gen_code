"""Atomic DEVS model: SeirdProcess (autonomous SEIRD discrete-time process).

- No DEVS ports (no input/output).
- Updates occur at times t = k*dt strictly less than simulation_time.
- Exactly one final JSONL record is printed to stdout at the simulation horizon.
- Any diagnostics go to stderr only.
"""

import json
import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class SeirdProcess(Atomic):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        test_name: str,
        mortality: float,
        infectivity_period: float,
        dt: float,
        incubation_period: float,
        total_population: int,
        initial_infective: int,
        transmission_rate: float,
        simulation_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Identification/logging only (not emitted to stdout)
        self.test_name = test_name

        # Parameters
        self.mortality = float(mortality)
        self.infectivity_period = float(infectivity_period)
        self.dt = float(dt)
        self.incubation_period = float(incubation_period)
        self.total_population = int(total_population)
        self.initial_infective = int(initial_infective)
        self.transmission_rate = float(transmission_rate)
        self.simulation_time = float(simulation_time)

        # State (floats)
        self.N = 0.0
        self.S = 0.0
        self.E = 0.0
        self.I = 0.0
        self.R = 0.0
        self.D = 0.0

        # Internal flags
        self._valid_init = True

    def _stderr(self, msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    def _validate_and_initialize_state(self) -> None:
        self._valid_init = True

        if self.dt <= 0.0:
            self._stderr(f"[SeirdProcess] Invalid dt={self.dt}. Must be > 0.")
            self._valid_init = False
        if self.incubation_period <= 0.0:
            self._stderr(
                f"[SeirdProcess] Invalid incubation_period={self.incubation_period}. Must be > 0."
            )
            self._valid_init = False
        if self.infectivity_period <= 0.0:
            self._stderr(
                f"[SeirdProcess] Invalid infectivity_period={self.infectivity_period}. Must be > 0."
            )
            self._valid_init = False
        if self.total_population < 0:
            self._stderr(
                f"[SeirdProcess] Invalid total_population={self.total_population}. Must be >= 0."
            )
            self._valid_init = False
        if not (0 <= self.initial_infective <= max(0, self.total_population)):
            self._stderr(
                "[SeirdProcess] Invalid initial_infective="
                f"{self.initial_infective}. Must satisfy 0 <= initial_infective <= total_population."
            )
            self._valid_init = False

        if self.mortality < 0.0 or self.mortality > 100.0:
            self._stderr(
                f"[SeirdProcess] Warning: mortality={self.mortality} outside [0,100]. Proceeding with mort_frac=mortality/100."
            )

        # Initialize compartments safely.
        if self.total_population == 0:
            # Validity rule implies initial_infective must be 0; if not, it was flagged invalid.
            self.N = 0.0
            self.S = 0.0
            self.E = 0.0
            self.I = 0.0
            self.R = 0.0
            self.D = 0.0
            return

        # If invalid, keep a conservative, well-defined state by clamping I0 into [0, N]
        # so initialization can complete without contradiction.
        N = float(max(0, self.total_population))
        I0 = float(self.initial_infective)
        if I0 < 0.0:
            I0 = 0.0
        if I0 > N:
            I0 = N

        self.N = N
        self.I = I0
        self.S = N - I0
        self.E = 0.0
        self.R = 0.0
        self.D = 0.0

    def _apply_population_correction_if_needed(self) -> None:
        total = self.S + self.E + self.I + self.R + self.D
        drift = self.N - total
        if abs(drift) <= 1e-9:
            return

        # Prefer correcting S minimally.
        corrected_S = self.S + drift
        if corrected_S < -1e-6:
            self._stderr(
                f"[SeirdProcess] Population drift correction would make S negative (S={self.S}, drift={drift}). "
                "Skipping correction."
            )
            return

        if corrected_S < 0.0:
            corrected_S = 0.0

        self._stderr(
            f"[SeirdProcess] Correcting population drift by adjusting S: drift={drift} (before sum={total}, N={self.N})."
        )
        self.S = corrected_S

    def _step_update(self) -> None:
        S_old, E_old, I_old, R_old, D_old = self.S, self.E, self.I, self.R, self.D

        # 1) S -> E
        if self.N > 0.0:
            new_exposed = (self.transmission_rate * S_old * I_old / self.N) * self.dt
        else:
            new_exposed = 0.0
        if new_exposed > S_old:
            new_exposed = S_old
        S_new = S_old - new_exposed

        # 2) E -> I
        new_infective = (E_old / self.incubation_period) * self.dt
        if new_infective > E_old:
            new_infective = E_old
        E_new = E_old + new_exposed - new_infective

        # 3) I -> D and I -> R
        mort_frac = self.mortality / 100.0
        new_deceased = (I_old / self.infectivity_period) * mort_frac * self.dt
        new_recovered = (I_old / self.infectivity_period) * (1.0 - mort_frac) * self.dt
        I_new = I_old + new_infective - new_deceased - new_recovered

        # 4) Accumulate outcomes
        R_new = R_old + new_recovered
        D_new = D_old + new_deceased

        self.S, self.E, self.I, self.R, self.D = S_new, E_new, I_new, R_new, D_new
        self._apply_population_correction_if_needed()

    def initialize(self):
        self._validate_and_initialize_state()

        # Scheduling:
        # - Updates at k*dt strictly less than simulation_time.
        # - Final observation at time=simulation_time (no update at endpoint).
        if self.simulation_time <= 0.0:
            self.hold_in("FINAL", 0.0)
            return

        if self.dt <= 0.0:
            # Invalid dt: perform no updates; still schedule final output at horizon.
            self.hold_in("FINAL", self.simulation_time)
            return

        if self.dt < self.simulation_time:
            self.hold_in("STEP", self.dt)
        else:
            self.hold_in("FINAL", self.simulation_time)

    def deltext(self, e: float):
        # Autonomous model: no input ports.
        self.continuef(e)

    def lambdaf(self):
        if self.phase != "FINAL":
            return

        # Time must be float with at least 2 decimals; ensure by formatting then float().
        time_val = float(f"{self.simulation_time:.2f}")
        record = {
            "time": time_val,
            "susceptible": round(self.S, 2),
            "exposed": round(self.E, 2),
            "infective": round(self.I, 2),
            "recovered": round(self.R, 2),
            "deceased": round(self.D, 2),
        }
        print(json.dumps(record), flush=True)

    def deltint(self):
        if self.phase == "FINAL":
            self.passivate("DONE")
            return

        # STEP phase: apply one update then decide next scheduling.
        self._step_update()

        now = get_current_time()
        next_update_time = now + self.dt

        if next_update_time < self.simulation_time:
            self.hold_in("STEP", self.dt)
        else:
            # Schedule final observation exactly at the horizon; no update at endpoint.
            self.hold_in("FINAL", max(0.0, self.simulation_time - now))

    def exit(self):
        # Final stdout emission is handled in lambdaf() at phase FINAL.
        pass