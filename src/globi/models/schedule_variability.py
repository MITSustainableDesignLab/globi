"""Seeded per-building variability for operational schedules.

Without this, every building resolving to the same SpaceUse record runs identical
schedules (a "city of robots"). The perturbations are applied after component lookup
and are reproducible from (seed, building_id).
"""

import hashlib
from collections.abc import Callable

import numpy as np
from epinterface.sbem.components.schedules import (
    DayComponent,
    TypeLimits,
    YearComponent,
)
from epinterface.sbem.components.space_use import ZoneSpaceUseComponent
from epinterface.sbem.fields.spec import CategoricalFieldSpec, SemanticModelFields
from pydantic import BaseModel, Field, model_validator

from globi.models.base import BaseConfig

HOURS = [f"Hour_{h:02d}" for h in range(24)]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
FEATURE_PREFIX = "feature.schedule_variability"


class VariabilityParams(BaseModel, extra="forbid"):
    """Noise strengths for one group of buildings."""

    time_shift_std_h: float = Field(
        default=0.0,
        ge=0,
        le=6,
        description="Std dev [h] of one per-building shift of occupancy, lighting, "
        "equipment and water-use profiles (clipped at 3 std).",
    )
    intensity_cv: float = Field(
        default=0.0,
        ge=0,
        le=2,
        description="Coefficient of variation of mean-1 lognormal multipliers on "
        "people density, lighting/equipment power density and DHW flow per person.",
    )
    hourly_noise_std: float = Field(
        default=0.0,
        ge=0,
        le=0.5,
        description="Std dev of additive AR(1) noise on each hour of the load "
        "schedules, clipped to the schedule type limits.",
    )
    hourly_noise_autocorr: float = Field(
        default=0.7,
        ge=0,
        lt=1,
        description="Hour-to-hour autocorrelation of the hourly noise.",
    )
    setpoint_offset_std_c: float = Field(
        default=0.0,
        ge=0,
        le=5,
        description="Std dev [C] of one per-building offset added to both heating "
        "and cooling setpoints (clipped at 3 std).",
    )


class ScheduleVariabilityConfig(BaseConfig):
    """Per-building schedule variability, optionally varied by a semantic field."""

    seed: int = Field(default=0, ge=0, description="Global seed for all draws.")
    semantic_field: str | None = Field(
        default=None,
        description="Semantic field whose value selects the `by_value` overrides.",
    )
    default: VariabilityParams = Field(default_factory=VariabilityParams)
    by_value: dict[str, dict[str, float]] = Field(
        default_factory=dict,
        description="Partial overrides of `default`, keyed by semantic field value.",
    )

    @model_validator(mode="after")
    def check_overrides(self):
        """Validate every override up front instead of at simulation time."""
        if self.by_value and self.semantic_field is None:
            msg = "`by_value` needs a `semantic_field` to select on."
            raise ValueError(msg)
        for value in self.by_value:
            self.params_for_value(value)
        return self

    def params_for_value(self, value: str) -> VariabilityParams:
        """Merge the override for one semantic field value onto the default."""
        override = self.by_value.get(value, {})
        return VariabilityParams.model_validate({
            **self.default.model_dump(),
            **override,
        })

    def params_for(self, context: dict[str, float | str | int]) -> VariabilityParams:
        """Pick the parameters for a building from its semantic field context."""
        if self.semantic_field is None:
            return self.default
        if self.semantic_field not in context:
            msg = (
                f"Schedule variability selects on semantic field "
                f"'{self.semantic_field}', which the building does not have "
                f"(fields: {sorted(context)})."
            )
            raise ValueError(msg)
        return self.params_for_value(str(context[self.semantic_field]))

    def check_semantic_fields(self, fields: SemanticModelFields) -> None:
        """Raise if `semantic_field` or a `by_value` key is not in the semantic fields.

        Run before submitting, so a typo fails once instead of on every worker, and a
        misspelled value does not silently fall back to `default`.
        """
        if self.semantic_field is None:
            return
        by_name = {f.Name: f for f in fields.Fields}
        field = by_name.get(self.semantic_field)
        if field is None:
            msg = (
                f"Schedule variability `semantic_field` '{self.semantic_field}' is not "
                f"in the semantic fields file (fields: {sorted(by_name)})."
            )
            raise ValueError(msg)
        if not self.by_value:
            return
        if not isinstance(field, CategoricalFieldSpec):
            msg = (
                f"Schedule variability `by_value` needs a categorical field, but "
                f"'{self.semantic_field}' is numeric."
            )
            raise TypeError(msg)
        options = [str(o) for o in field.Options]
        unknown = sorted(set(self.by_value) - set(options))
        if unknown:
            msg = (
                f"Schedule variability `by_value` keys {unknown} are not options of "
                f"'{self.semantic_field}' (options: {options})."
            )
            raise ValueError(msg)


def seeded_rng(seed: int, *keys: str) -> np.random.Generator:
    """A generator that depends only on the seed and the string keys."""
    # sha256, not hash(): python's str hash is salted per process.
    digests = [
        int.from_bytes(hashlib.sha256(k.encode()).digest()[:8], "little") for k in keys
    ]
    return np.random.default_rng([seed, *digests])


def _clipped_normal(rng: np.random.Generator, std: float) -> float:
    return float(np.clip(rng.normal(0, std), -3 * std, 3 * std))


def _mean_one_lognormal(rng: np.random.Generator, cv: float) -> float:
    sigma = np.sqrt(np.log1p(cv**2))
    return float(rng.lognormal(-(sigma**2) / 2, sigma))


def _ar1(rng: np.random.Generator, std: float, rho: float) -> np.ndarray:
    eps = rng.normal(0, std, 24)
    out = np.empty(24)
    out[0] = eps[0]
    for t in range(1, 24):
        out[t] = rho * out[t - 1] + np.sqrt(1 - rho**2) * eps[t]
    return out


def shift_values(values: np.ndarray, shift_h: float) -> np.ndarray:
    """Circularly shift a 24-h profile later by `shift_h` hours; preserves the sum."""
    hours = np.arange(24)
    return np.interp((hours - shift_h) % 24, hours, values, period=24)


def _perturb_year(
    year: YearComponent, perturb_day: Callable[[DayComponent], DayComponent]
) -> YearComponent:
    weeks = {}
    for month in MONTHS:
        week = getattr(year, month)
        weeks[month] = week.model_copy(
            update={d: perturb_day(getattr(week, d)) for d in DAYS}
        )
    return year.model_copy(update=weeks)


def perturb_space_use(
    space_use: ZoneSpaceUseComponent,
    params: VariabilityParams,
    seed: int,
    building_id: str,
) -> tuple[ZoneSpaceUseComponent, dict[str, float]]:
    """Return a perturbed copy of `space_use` and the per-building draws.

    Each draw has its own stream, so changing one noise strength leaves the others'
    draws unchanged.
    """

    def rng(*keys: str) -> np.random.Generator:
        return seeded_rng(seed, building_id, *keys)

    shift = _clipped_normal(rng("time_shift"), params.time_shift_std_h)
    offset = _clipped_normal(rng("setpoint_offset"), params.setpoint_offset_std_c)
    scales = {
        load: _mean_one_lognormal(rng(f"{load}_scale"), params.intensity_cv)
        for load in ("occupancy", "lighting", "equipment", "dhw")
    }

    # IDF schedules are de-duplicated by name, so each Day name gets one perturbation.
    cache: dict[str, DayComponent] = {}

    def perturb_day(day: DayComponent) -> DayComponent:
        if day.Name in cache:
            return cache[day.Name]
        values = np.array(day.Values)
        if day.Type == "Temperature":
            values = values + offset
        else:
            values = shift_values(values, shift)
            if params.hourly_noise_std > 0:
                values = values + _ar1(
                    rng("day", day.Name),
                    params.hourly_noise_std,
                    params.hourly_noise_autocorr,
                )
        limits = TypeLimits[day.Type]
        values = np.clip(values, limits.Lower_Limit_Value, limits.Upper_Limit_Value)
        cache[day.Name] = day.model_copy(
            update=dict(zip(HOURS, values.tolist(), strict=True))
        )
        return cache[day.Name]

    su = space_use
    perturbed = su.model_copy(
        update={
            "Occupancy": su.Occupancy.model_copy(
                update={
                    "PeopleDensity": su.Occupancy.PeopleDensity * scales["occupancy"],
                    "Schedule": _perturb_year(su.Occupancy.Schedule, perturb_day),
                }
            ),
            "Lighting": su.Lighting.model_copy(
                update={
                    "PowerDensity": su.Lighting.PowerDensity * scales["lighting"],
                    "Schedule": _perturb_year(su.Lighting.Schedule, perturb_day),
                }
            ),
            "Equipment": su.Equipment.model_copy(
                update={
                    "PowerDensity": su.Equipment.PowerDensity * scales["equipment"],
                    "Schedule": _perturb_year(su.Equipment.Schedule, perturb_day),
                }
            ),
            "WaterUse": su.WaterUse.model_copy(
                update={
                    "FlowRatePerPerson": su.WaterUse.FlowRatePerPerson * scales["dhw"],
                    "Schedule": _perturb_year(su.WaterUse.Schedule, perturb_day),
                }
            ),
            "Thermostat": su.Thermostat.model_copy(
                update={
                    "HeatingSetpoint": su.Thermostat.HeatingSetpoint + offset,
                    "CoolingSetpoint": su.Thermostat.CoolingSetpoint + offset,
                    "HeatingSchedule": _perturb_year(
                        su.Thermostat.HeatingSchedule, perturb_day
                    ),
                    "CoolingSchedule": _perturb_year(
                        su.Thermostat.CoolingSchedule, perturb_day
                    ),
                }
            ),
        }
    )
    draws = {
        f"{FEATURE_PREFIX}.time_shift_h": shift,
        **{f"{FEATURE_PREFIX}.{load}_scale": s for load, s in scales.items()},
        f"{FEATURE_PREFIX}.setpoint_offset_c": offset,
    }
    return perturbed, draws
