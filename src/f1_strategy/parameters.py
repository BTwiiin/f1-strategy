"""Model-agnostic parameter interface shared by estimation and simulation.

A ``ParameterSet`` holds lookup tables over joint sample IDs: every array's first axis is
the sample, so pace offsets, all compounds' tyre-age tables and pit-loss samples of one
bootstrap sample stay aligned. Only per-lap effects are stored; cumulative stint losses
are derived by the simulator and never stored.
"""

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

FALLBACK_LEVELS = ("circuit", "global")
PIT_LOSS_KEY = "pit_loss"
_ABSOLUTE_COMPOUND = re.compile(r"C[0-6]")


def check_compounds(compounds: Sequence[str]) -> None:
    """Raise ``ValueError`` unless ``compounds`` are unique absolute designations C0-C6."""
    if not compounds:
        raise ValueError("at least one compound is required")
    if len(set(compounds)) != len(compounds):
        raise ValueError(f"duplicate compounds: {compounds}")
    bad = [c for c in compounds if not (isinstance(c, str) and _ABSOLUTE_COMPOUND.fullmatch(c))]
    if bad:
        raise ValueError(f"compounds must be absolute designations C0-C6, got {bad}")


def _frozen(a: np.ndarray, dtype=float) -> np.ndarray:
    a = np.array(a, dtype=dtype)
    a.setflags(write=False)
    return a


@dataclass(frozen=True)
class ParameterSet:
    """Tyre and pit parameters for one common-trend scenario.

    Shapes (B samples, C compounds, A = maximum tabulated tyre age):

    - ``pace_offset`` (B, C): s/lap of each compound at ``reference_age``.
    - ``age_effect`` (B, C, A): per-lap lap-time effect at tyre age ``a`` in index ``a - 1``
      (tyre age 1 = first lap on a new set), exactly zero at ``reference_age``.
    - ``pit_loss`` (B,): incremental time per green-flag stop relative to normal in- and
      out-laps on the same tyres.
    - ``sample_ids`` (B,): unique joint bootstrap sample IDs.

    ``scenario`` is the ``common_trend_gain`` (s/lap) the tyre parameters were estimated
    under; ``fallback_level`` maps every compound and ``"pit_loss"`` to ``circuit`` or
    ``global``.
    """

    compounds: tuple[str, ...]
    reference_age: int
    pace_offset: np.ndarray
    age_effect: np.ndarray
    pit_loss: np.ndarray
    sample_ids: np.ndarray
    scenario: float
    fallback_level: Mapping[str, str]
    provenance: str

    def __post_init__(self) -> None:
        compounds = tuple(self.compounds)
        check_compounds(compounds)
        ids = np.asarray(self.sample_ids)
        if ids.ndim != 1 or not np.issubdtype(ids.dtype, np.integer):
            raise ValueError("sample_ids must be a 1-d integer array")
        if len(np.unique(ids)) != len(ids) or len(ids) == 0:
            raise ValueError("sample_ids must be non-empty and unique")
        b, c = len(ids), len(compounds)
        pace = _frozen(self.pace_offset)
        age = _frozen(self.age_effect)
        pit = _frozen(self.pit_loss)
        if pace.shape != (b, c):
            raise ValueError(f"pace_offset shape {pace.shape} != {(b, c)}")
        if age.ndim != 3 or age.shape[:2] != (b, c) or age.shape[2] == 0:
            raise ValueError(f"age_effect shape {age.shape} != {(b, c)} + (max_age,)")
        if pit.shape != (b,):
            raise ValueError(f"pit_loss shape {pit.shape} != {(b,)}")
        for name, a in (("pace_offset", pace), ("age_effect", age), ("pit_loss", pit)):
            if not np.all(np.isfinite(a)):
                raise ValueError(f"{name} contains non-finite values")
        ref = self.reference_age
        if not (isinstance(ref, int) and 1 <= ref <= age.shape[2]):
            raise ValueError(f"reference_age must be an integer in [1, {age.shape[2]}]")
        if np.any(age[:, :, ref - 1] != 0):
            raise ValueError("age_effect must be exactly zero at the reference age")
        expected = {*compounds, PIT_LOSS_KEY}
        if set(self.fallback_level) != expected:
            raise ValueError(f"fallback_level keys must be {sorted(expected)}")
        if not set(self.fallback_level.values()) <= set(FALLBACK_LEVELS):
            raise ValueError(f"fallback levels must be in {FALLBACK_LEVELS}")
        if not math.isfinite(self.scenario):
            raise ValueError("scenario must be finite")
        if not (isinstance(self.provenance, str) and self.provenance):
            raise ValueError("provenance must be a non-empty string")

        object.__setattr__(self, "compounds", compounds)
        object.__setattr__(self, "pace_offset", pace)
        object.__setattr__(self, "age_effect", age)
        object.__setattr__(self, "pit_loss", pit)
        object.__setattr__(self, "sample_ids", _frozen(ids, dtype=ids.dtype))
        object.__setattr__(self, "fallback_level", dict(self.fallback_level))

    @property
    def n_samples(self) -> int:
        return len(self.sample_ids)

    @property
    def max_age(self) -> int:
        return self.age_effect.shape[2]

    def compound_index(self, compound: str) -> int:
        try:
            return self.compounds.index(compound)
        except ValueError:
            raise ValueError(f"no parameters for compound {compound}") from None

    def select(self, idx: Sequence[int] | np.ndarray) -> ParameterSet:
        """Subset of samples by position; all components stay aligned."""
        idx = np.asarray(idx)
        return ParameterSet(
            compounds=self.compounds,
            reference_age=self.reference_age,
            pace_offset=self.pace_offset[idx],
            age_effect=self.age_effect[idx],
            pit_loss=self.pit_loss[idx],
            sample_ids=self.sample_ids[idx],
            scenario=self.scenario,
            fallback_level=self.fallback_level,
            provenance=self.provenance,
        )
