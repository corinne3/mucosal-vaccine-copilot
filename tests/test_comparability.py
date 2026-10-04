"""Objective 4 — the comparability engine is the project's main claim, so it gets
the strictest tests. A false 'comparable' is the worst failure mode here."""

from __future__ import annotations

import pandas as pd
import pytest

from mvc.comparability import (
    Level,
    audit_table,
    comparability_matrix,
    compare,
    explain,
    harmonize_units,
)
from mvc.eval.run import COMPARABILITY_CASES, _ctx
from mvc.synthetic import demo_dataset


def test_identical_contexts_are_comparable():
    r = compare(_ctx(), _ctx())
    assert r.level is Level.comparable and not r.flags


@pytest.mark.parametrize("a,b,expected", COMPARABILITY_CASES,
                         ids=[f"{i}" for i in range(len(COMPARABILITY_CASES))])
def test_labelled_pairs(a, b, expected):
    assert compare(a, b).label == expected


def test_compare_is_symmetric():
    for a, b, _ in COMPARABILITY_CASES:
        assert compare(a, b).label == compare(b, a).label


def test_cross_compartment_never_comparable():
    """Mucosal vs systemic absolute values must never pass as comparable."""
    r = compare(_ctx(), _ctx(compartment="serum", method="serum"))
    assert r.level is Level.not_comparable
    assert any(f.code == "COMPARTMENT" for f in r.flags)
    assert "fold-rise" in explain(r)


def test_saliva_is_mucosal_but_not_nasal():
    r = compare(_ctx(compartment="nasal", method="nasosorption"),
                _ctx(compartment="oral", method="saliva"))
    assert r.level is Level.not_comparable


def test_normalisation_rescues_different_devices():
    """Raw lavage vs strip: not comparable. Both normalised to total IgA: conditional."""
    raw = compare(_ctx(method="nasal_wash"), _ctx(method="nasosorption"))
    norm = compare(_ctx(method="nasal_wash", normalization="total_iga", unit="ratio"),
                   _ctx(method="nasosorption", normalization="total_iga", unit="ratio"))
    assert raw.level is Level.not_comparable
    assert norm.level is Level.conditional


def test_synthetic_never_mixes_with_measured():
    r = compare(_ctx(source="measured"), _ctx(source="synthetic"))
    assert r.level is Level.not_comparable
    assert any(f.code == "SYNTHETIC_MIX" for f in r.flags)


def test_digitized_is_flagged_conditional():
    r = compare(_ctx(), _ctx(source="digitized_from_figure"))
    assert r.level is Level.conditional
    assert any(f.code == "DIGITIZED" for f in r.flags)


def test_every_flag_has_message_and_remedy():
    for a, b, _ in COMPARABILITY_CASES:
        for f in compare(a, b).flags:
            assert f.message.strip() and f.code.strip()
            if f.level is Level.not_comparable:
                assert f.remedy.strip(), f"{f.code} must suggest a remedy"


def test_unit_conversion_is_applied():
    df = pd.DataFrame([{"unit": "ng_ml", "value": 1000.0}, {"unit": "ug_ml", "value": 2.0}])
    out = harmonize_units(df, target="ug_ml")
    assert set(out["unit"]) == {"ug_ml"}
    assert out["value"].tolist() == [1.0, 2.0]


def test_matrix_is_square_and_symmetric():
    df = demo_dataset(n=6)
    mat, details = comparability_matrix(df)
    assert mat.shape[0] == mat.shape[1] == 6
    assert (mat.to_numpy() == mat.to_numpy().T).all()
    assert all(mat.iloc[i, i] == "comparable" for i in range(len(mat)))
    assert details


def test_audit_detects_thin_series_and_lloq():
    df = demo_dataset(n=8)
    a = audit_table(df)
    assert len(a) == 6
    thin = a[a["n_timepoints"] < 4]
    assert len(thin) >= 1
    assert all(any("timepoints" in f for f in flags) for flags in thin["flags"])
    assert set(a["uncertainty"]) <= {"low", "medium", "high"}


def test_audit_flags_missing_baseline():
    df = demo_dataset(n=5)
    df = df[df["day"] != 0]
    a = audit_table(df)
    assert any(any("baseline" in f for f in flags) for flags in a["flags"])
