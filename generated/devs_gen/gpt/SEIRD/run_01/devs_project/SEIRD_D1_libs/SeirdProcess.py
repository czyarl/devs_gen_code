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

        self.test_name = test_name
        self.mortality = float(mortality)
        self.infectivity_period = float(infectivity_period)
        self.dt = float(dt)
        self.incubation_period = float(incubation_period)
        self.total_population = total_population
        self.initial_infective = initial_infective
        self.transmission_rate = float(transmission_rate)
        self.simulation_time = float(simulation_time)

        self.N: int = 0
        self.S: float = 0.0
        self.E: float = 0.0
        self.I: float = 0.0
        self.R: float = 0.0
        self.D: float = 0.0

        self.next_update_time: float = 0.0
        self.final_emitted: bool = False

    def _validate_or_raise(self) -> None:
        errors: list[str] = []

        if not isinstance(self.total_population, int):
            errors.append(f"total_population must be int, got {type(self.total_population).__name__}")
        else:
            if self.total_population < 0:
                errors.append(f"total_population must be >= 0, got {self.total_population}")

        if self.dt <= 0:
            errors.append(f"dt must be > 0, got {self.dt}")
        if self.incubation_period <= 0:
            errors.append(f"incubation_period must be > 0, got {self.incubation_period}")
        if self.infectivity_period <= 0:
            errors.append(f"infectivity_period must be > 0, got {self.infectivity_period}")

        if not isinstance(self.initial_infective, int):
            errors.append(f"initial_infective must be int, got {type(self.initial_infective).__name__}")
        else:
            if isinstance(self.total_population, int):
                if self.initial_infective < 0 or self.initial_infective > self.total_population:
                    errors.append(
                        f"initial_infective must satisfy 0 <= initial_infective <= total_population, "
                        f"got initial_infective={self.initial_infective}, total_population={self.total_population}"
                    )

        if errors:
            for msg in errors:
                print(f"[SeirdProcess validation error] {msg}", file=sys.stderr, flush=True)
            raise ValueError("; ".join(errors))

        if self.mortality < 0.0 or self.mortality > 100.0:
            print(
                f"[SeirdProcess warning] mortality is outside typical [0, 100] percent range: {self.mortality}",
                file=sys.stderr,
                flush=True,
            )

    @staticmethod
    def _clamp_nonnegative(x: float, tol: float = 1e-12) -> float:
        if x < 0.0 and x > -tol:
            return 0.0
        return x

    def _apply_population_conservation(self) -> None:
        tol = 1e-9
        self.S = self._clamp_nonnegative(self.S)
        self.E = self._clamp_nonnegative(self.E)
        self.I = self._clamp_nonnegative(self.I)
        self.R = self._clamp_nonnegative(self.R)
        self.D = self._clamp_nonnegative(self.D)

        total = self.S + self.E + self.I + self.R + self.D
        drift = float(self.N) - total
        if abs(drift) > tol:
            # Minimal deterministic adjustment: recompute S from N - (E+I+R+D)
            corrected_S = float(self.N) - (self.E + self.I + self.R + self.D)
            if corrected_S < 0.0 and corrected_S > -1e-7:
                corrected_S = 0.0
            if corrected_S < 0.0:
                # If correction would go negative, clamp and accept residual drift.
                print(
                    f"[SeirdProcess warning] conservation correction would make S negative "
                    f"(computed {corrected_S}); clamping to 0. Drift={drift}",
                    file=sys.stderr,
                    flush=True,
                )
                corrected_S = 0.0
            else:
                print(
                    f"[SeirdProcess warning] population drift corrected deterministically. Drift={drift}",
                    file=sys.stderr,
                    flush=True,
                )
            self.S = corrected_S

    def _step_update(self) -> None:
        S_old, E_old, I_old, R_old, D_old = self.S, self.E, self.I, self.R, self.D
        N = self.N

        if N == 0:
            new_exposed = 0.0
        else:
            new_exposed = (self.transmission_rate * S_old * I_old / N) * self.dt
            if new_exposed > S_old:
                new_exposed = S_old

        new_infective = (E_old / self.incubation_period) * self.dt
        if new_infective > E_old:
            new_infective = E_old

        mort_frac = self.mortality / 100.0
        new_deceased = (I_old / self.infectivity_period) * mort_frac * self.dt
        new_recovered = (I_old / self.infectivity_period) * (1.0 - mort_frac) * self.dt

        S_new = S_old - new_exposed
        E_new = E_old + new_exposed - new_infective
        I_new = I_old + new_infective - new_deceased - new_recovered
        R_new = R_old + new_recovered
        D_new = D_old + new_deceased

        self.S, self.E, self.I, self.R, self.D = S_new, E_new, I_new, R_new, D_new
        self._apply_population_conservation()

    def initialize(self):
        self._validate_or_raise()

        self.N = int(self.total_population)
        I0 = float(self.initial_infective)

        if self.N == 0:
            self.S = self.E = self.I = self.R = self.D = 0.0
        else:
            self.S = float(self.N) - I0
            self.E = 0.0
            self.I = I0
            self.R = 0.0
            self.D = 0.0

        self._apply_population_conservation()
        self.final_emitted = False

        # Schedule updates at t = k*dt for k>=1 and t < simulation_time.
        # No update at t == simulation_time.
        if self.simulation_time <= 0.0:
            self.next_update_time = self.simulation_time
            self.hold_in("FINAL", 0.0)
            return

        if self.dt < self.simulation_time:
            self.next_update_time = self.dt
            self.hold_in("STEP", self.dt)
        else:
            # No updates occur; schedule final observation at simulation_time.
            self.next_update_time = self.simulation_time
            self.hold_in("FINAL", self.simulation_time)

    def deltext(self, e: float):
        # Autonomous model: no input ports.
        self.continuef(e)

    def lambdaf(self):
        # No DEVS ports; external stdout emission happens in exit().
        return

    def deltint(self):
        if self.phase == "STEP":
            self._step_update()

            now = get_current_time()
            next_time = now + self.dt
            self.next_update_time = next_time

            if next_time < self.simulation_time:
                self.hold_in("STEP", self.dt)
            else:
                # Schedule final observation at simulation_time without applying an update there.
                self.hold_in("FINAL", max(0.0, self.simulation_time - now))
            return

        if self.phase == "FINAL":
            self.passivate("DONE")
            return

        self.passivate("DONE")

    def exit(self):
        if self.final_emitted:
            return

        record = {
            "time": float(f"{self.simulation_time:.2f}"),
            "susceptible": float(f"{self.S:.2f}"),
            "exposed": float(f"{self.E:.2f}"),
            "infective": float(f"{self.I:.2f}"),
            "recovered": float(f"{self.R:.2f}"),
            "deceased": float(f"{self.D:.2f}"),
        }
        print(json.dumps(record), flush=True)
        self.final_emitted = True