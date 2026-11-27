import numpy as np
import pytest

from f1_strategy.parameters import ParameterSet


def _linear_params(
    offsets,
    degradation,
    pit_loss,
    reference_age=2,
    max_age=60,
    scenario=0.06,
):
    """ParameterSet with linear per-lap effects ``d_c * (age - reference_age)``.

    ``offsets``/``degradation`` map compound -> value, or -> sequence over samples.
    """
    compounds = tuple(offsets)
    pit = np.atleast_1d(np.asarray(pit_loss, dtype=float))
    n = max(
        len(pit),
        *(np.size(v) for v in offsets.values()),
        *(np.size(v) for v in degradation.values()),
    )
    ages = np.arange(1, max_age + 1)
    pace = np.column_stack([np.broadcast_to(offsets[c], n) for c in compounds])
    slope = np.column_stack([np.broadcast_to(degradation[c], n) for c in compounds])
    return ParameterSet(
        compounds=compounds,
        reference_age=reference_age,
        pace_offset=pace,
        age_effect=slope[:, :, None] * (ages - reference_age),
        pit_loss=np.broadcast_to(pit, n),
        sample_ids=np.arange(n),
        scenario=scenario,
        fallback_level={**dict.fromkeys(compounds, "circuit"), "pit_loss": "circuit"},
        provenance="test:linear",
    )


@pytest.fixture
def linear_params():
    return _linear_params
