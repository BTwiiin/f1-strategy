import numpy as np
import pytest

from f1_strategy.parameters import ParameterSet


def kwargs(b=3, compounds=("C2", "C3"), max_age=10, ref=2):
    age = np.tile(np.arange(1, max_age + 1, dtype=float) - ref, (b, len(compounds), 1))
    return {
        "compounds": compounds,
        "reference_age": ref,
        "pace_offset": np.zeros((b, len(compounds))),
        "age_effect": age * 0.1,
        "pit_loss": np.full(b, 20.0),
        "sample_ids": np.arange(b),
        "scenario": 0.06,
        "fallback_level": {**dict.fromkeys(compounds, "global"), "pit_loss": "circuit"},
        "provenance": "test",
    }


def test_valid_parameter_set():
    p = ParameterSet(**kwargs())
    assert (p.n_samples, p.max_age) == (3, 10)
    assert p.compound_index("C3") == 1
    with pytest.raises(ValueError):
        p.pace_offset[0, 0] = 1.0  # arrays are read-only


def test_select_keeps_joint_alignment():
    k = kwargs()
    k["pit_loss"] = np.array([19.0, 20.0, 21.0])
    k["pace_offset"] = np.array([[0.1, 0.0], [0.2, 0.0], [0.3, 0.0]])
    k["sample_ids"] = np.array([7, 8, 9])
    sub = ParameterSet(**k).select([2, 0])
    assert sub.sample_ids.tolist() == [9, 7]
    assert sub.pit_loss.tolist() == [21.0, 19.0]
    assert sub.pace_offset[:, 0].tolist() == [0.3, 0.1]


def _with(**changes):
    k = kwargs()
    k.update(changes)
    return k


@pytest.mark.parametrize(
    "bad",
    [
        _with(compounds=("C2", "C2")),  # duplicate compound
        _with(compounds=("C2", "SOFT")),  # not an absolute compound
        _with(compounds=()),
        _with(sample_ids=np.array([0, 1, 1])),  # duplicate sample id
        _with(sample_ids=np.array([0.0, 1.0, 2.0])),  # non-integer ids
        _with(pit_loss=np.full(2, 20.0)),  # misaligned B
        _with(pace_offset=np.zeros((3, 3))),  # wrong compound dimension
        _with(age_effect=np.zeros((3, 2))),  # wrong ndim
        _with(pace_offset=np.full((3, 2), np.nan)),
        _with(reference_age=0),
        _with(reference_age=11),  # beyond the table
        _with(age_effect=np.ones((3, 2, 10))),  # non-zero at the reference age
        _with(fallback_level={"C2": "global", "C3": "global"}),  # pit_loss missing
        _with(fallback_level={"C2": "global", "C3": "group", "pit_loss": "global"}),
        _with(scenario=float("nan")),
        _with(provenance=""),
    ],
)
def test_invalid_parameter_set_raises(bad):
    with pytest.raises(ValueError):
        ParameterSet(**bad)
