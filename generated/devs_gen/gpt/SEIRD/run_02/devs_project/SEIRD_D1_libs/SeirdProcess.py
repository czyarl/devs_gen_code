import json
import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class SeirdProcess(Atomic):
    """
    Closed-population SEIRD compartmental epidemic process with homogeneous mixing.
    Autonomous discrete-time updates at fixed step dt for times k*dt < simulation_time.
    Emits exactly one final JSONL record to stdout at end-of-simulation.
    """

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

        # Configuration
        self.test_name = test_name
        self.mortality = float(mortality)
        self.infectivity_period = float(infectivity_period)
        self.dt = float(dt)
        self.incubation_period = float(incubation_period)
        self.total_population = int(total_population)
        self.initial_infective = int(initial_infective)
        self.transmission_rate = float(transmission_rate)
        self.simulation_time = float(simulation_time)

        # State (floats)
        self.susceptible = 0.0
        self.exposed = 0.0
        self.infective = 0.0
        self.recovered = 0.0
        self.deceased = 0.0

        self._validation_ok = True

    def _log_err(self, msg: str) -> None:
        print(f"[SeirdProcess:{self.test_name}] {msg}", file=sys.stderr, flush=True)

    def _validate_and_initialize_state(self) -> None:
        self._validation_ok = True

        if self.total_population < 0:
            self._validation_ok = False
            self._log_err(f"Invalid total_population={self.total_population} (must be >= 0).")

        if self.simulation_time < 0.0:
            self._validation_ok = False
            self._log_err(f"Invalid simulation_time={self.simulation_time} (must be >= 0).")

        if self.dt <= 0.0:
            self._validation_ok = False
            self._log_err(f"Invalid dt={self.dt} (must be > 0).")

        if self.incubation_period <= 0.0:
            self._validation_ok = False
            self._log_err(f"Invalid incubation_period={self.incubation_period} (must be > 0).")

        if self.infectivity_period <= 0.0:
            self._validation_ok = False
            self._log_err(f"Invalid infectivity_period={self.infectivity_period} (must be > 0).")

        if not (0 <= self.initial_infective <= self.total_population):
            self._validation_ok = False
            self._log_err(
                f"Invalid initial_infective={self.initial_infective} "
                f"(must satisfy 0 <= initial_infective <= total_population={self.total_population}). "
                "Clamping to safe range."
            )
            if self.total_population < 0:
                # If total_population invalid, clamp infective to 0 as safest.
                self.initial_infective = 0
            else:
                self.initial_infective = max(0, min(self.initial_infective, self.total_population))

        m = self.mortality / 100.0
        if m < 0.0 or m > 1.0:
            self._log_err(f"Warning: mortality={self.mortality} implies m={m} outside [0,1]; applying as given.")

        # Initialize compartments (well-defined with clamped initial_infective and nonnegative N)
        N = max(0, self.total_population)
        i0 = max(0, min(self.initial_infective, N))
        self.susceptible = float(N - i0)
        self.exposed = 0.0
        self.infective = float(i0)
        self.recovered = 0.0
        self.deceased = 0.0

        # If total_population was invalid negative, keep N=0 baseline
        if self.total_population < 0:
            self.total_population = 0

    def initialize(self):
        self._validate_and_initialize_state()

        # Schedule updates at dt, 2dt, ... strictly less than simulation_time.
        # Always schedule a FINAL observation at simulation_time (or immediately if <= 0).
        if self.simulation_time <= 0.0:
            self.hold_in("FINAL", 0.0)
            return

        if self.dt > 0.0 and self.dt < self.simulation_time:
            self.hold_in("STEP", self.dt)
        else:
            # No internal updates occur; schedule final observation at simulation_time.
            self.hold_in("FINAL", self.simulation_time)

    def deltext(self, e: float):
        # Autonomous model has no input ports.
        self.continuef(e)

    def lambdaf(self):
        if self.phase != "FINAL":
            return

        record = {
            "time": float(round(float(self.simulation_time), 2)),
            "susceptible": float(round(self.susceptible, 2)),
            "exposed": float(round(self.exposed, 2)),
            "infective": float(round(self.infective, 2)),
            "recovered": float(round(self.recovered, 2)),
            "deceased": float(round(self.deceased, 2)),
        }
        print(json.dumps(record), flush=True)

    def _apply_update(self) -> None:
        S_old = float(self.susceptible)
        E_old = float(self.exposed)
        I_old = float(self.infective)
        R_old = float(self.recovered)
        D_old = float(self.deceased)

        N = int(self.total_population)

        # 1) S -> E
        if N == 0:
            new_exposed = 0.0
            self._log_err("Warning: total_population N==0; setting new_exposed=0.0 to avoid division by zero.")
        else:
            new_exposed = (self.transmission_rate * S_old * I_old / float(N)) * self.dt
            if new_exposed > S_old:
                new_exposed = S_old
        S_new = S_old - new_exposed

        # 2) E -> I
        new_infective = (E_old / self.incubation_period) * self.dt
        if new_infective > E_old:
            new_infective = E_old
        E_new = E_old + new_exposed - new_infective

        # 3) I -> D and I -> R
        m = self.mortality / 100.0
        new_deceased = (I_old / self.infectivity_period) * m * self.dt
        new_recovered = (I_old / self.infectivity_period) * (1.0 - m) * self.dt
        I_new = I_old + new_infective - new_deceased - new_recovered

        # 4) Accumulate R and D
        R_new = R_old + new_recovered
        D_new = D_old + new_deceased

        # Numerical hygiene: clamp tiny negatives
        def clamp_nonneg(x: float, name: str) -> float:
            if x < 0.0 and x > -1e-12:
                self._log_err(f"Clamping tiny negative {name}={x} to 0.0 due to numeric drift.")
                return 0.0
            return x

        S_new = clamp_nonneg(S_new, "susceptible")
        E_new = clamp_nonneg(E_new, "exposed")
        I_new = clamp_nonneg(I_new, "infective")
        R_new = clamp_nonneg(R_new, "recovered")
        D_new = clamp_nonneg(D_new, "deceased")

        # Conservation correction (optional): adjust S by residual
        total = S_new + E_new + I_new + R_new + D_new
        residual = float(N) - total
        if abs(residual) > 1e-9:
            # Minimal correction: adjust susceptible
            S_new += residual
            if abs(residual) > 1e-6:
                self._log_err(f"Correcting conservation drift by residual={residual} applied to susceptible.")
            if S_new < 0.0 and S_new > -1e-12:
                self._log_err(f"Clamping tiny negative susceptible after correction S={S_new} to 0.0.")
                S_new = 0.0

        self.susceptible = float(S_new)
        self.exposed = float(E_new)
        self.infective = float(I_new)
        self.recovered = float(R_new)
        self.deceased = float(D_new)

    def deltint(self):
        if self.phase == "FINAL":
            self.passivate("DONE")
            return

        if self.phase == "STEP":
            self._apply_update()

            now = float(get_current_time())
            next_update_time = now + self.dt

            if next_update_time < self.simulation_time:
                self.hold_in("STEP", self.dt)
            else:
                # Do not apply another update at the right endpoint; schedule final observation there.
                self.hold_in("FINAL", max(0.0, self.simulation_time - now))
            return

        # Fallback: if in unknown phase, go to FINAL at horizon.
        now = float(get_current_time())
        self.hold_in("FINAL", max(0.0, self.simulation_time - now))

    def exit(self):
        # No required external IO here; final stdout record is emitted in lambdaf() at FINAL.
        pass