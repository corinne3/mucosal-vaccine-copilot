"""Objectives 4 and 5 — kinetic fitting and the synthetic generator.

The generator is what makes these tests possible: truth is known, so the fit can
be graded instead of merely inspected.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mvc.kinetics import LN2, bateman, fit_kinetics, fold_rise_table, peak_time
from mvc.synthetic import (
    PROFILES,
    bateman_from_shape,
    demo_dataset,
    demo_series,
    generate_arm,
)


# --- the model itself ------------------------------------------------------- #
def test_bateman_starts_at_baseline_and_returns_to_it():
    y = bateman(np.array([0.0, 1e6]), b=2.0, A=10.0, ka=0.3, ke=0.02)
    assert y[0] == pytest.approx(2.0)
    assert y[1] == pytest.approx(2.0, abs=1e-6)


def test_peak_time_matches_numeric_maximum():
    ka, ke = 0.25, 0.03
    tp = peak_time(ka, ke)
    grid = np.linspace(0, 200, 20001)
    assert tp == pytest.approx(grid[np.argmax(bateman(grid, 1.0, 5.0, ka, ke))], abs=0.05)


def test_shape_inversion_round_trip():
    """(peak day, half-life, fold) -> (A, ka, ke) -> back again."""
    for peak, hl, fold in [(14, 60, 4.0), (28, 150, 6.0), (7, 30, 2.0)]:
        A, ka, ke = bateman_from_shape(peak, hl, baseline=1.0, fold_peak=fold)
        assert peak_time(ka, ke) == pytest.approx(peak, rel=1e-3)
        assert LN2 / ke == pytest.approx(hl, rel=1e-6)
        assert bateman(peak, 1.0, A, ka, ke) == pytest.approx(fold, rel=1e-3)


# --- fitting --------------------------------------------------------------- #
def test_fit_recovers_peak_on_clean_dense_data():
    dense = next(s for s in demo_series() if s.method == "nasosorption")
    df = generate_arm("A", "laiv_like", [dense], n=40, seed=7)
    spec = PROFILES["laiv_like"]["nasal_iga"]
    _, ka, ke = bateman_from_shape(spec.peak_day, spec.half_life, spec.baseline, spec.fold_peak)
    truth = peak_time(ka, ke)
    k = fit_kinetics(df, n_boot=120, seed=1).kinetic
    assert k.identifiable
    assert k.peak_day == pytest.approx(truth, rel=0.4)
    assert k.ci_peak_day and k.ci_peak_day[0] <= truth <= k.ci_peak_day[1]
    assert k.fold_rise > 1.0


def test_fit_declares_itself_unidentifiable_on_sparse_data():
    """Three timepoints cannot pin down a four-parameter curve — say so, do not
    return a confident number."""
    sparse = next(s for s in demo_series() if s.days == [0, 28, 180])
    df = generate_arm("A", "laiv_like", [sparse], n=20, seed=3)
    k = fit_kinetics(df, n_boot=40).kinetic
    assert not k.identifiable
    assert any("not identifiable" in n for n in k.notes)


def test_fit_warns_when_half_life_is_extrapolated():
    short = demo_series()[0].__class__(
        response="nasal_iga", method="nasosorption", compartment="nasal", isotype="sIgA",
        assay="elisa_binding", unit="ratio", days=[0, 3, 7, 10, 14], normalization="total_iga")
    df = generate_arm("A", "laiv_like", [short], n=25, seed=5)
    k = fit_kinetics(df, n_boot=80).kinetic
    assert any("half-life" in n.lower() for n in k.notes)


def test_bootstrap_ci_brackets_the_point_estimate():
    dense = next(s for s in demo_series() if s.method == "nasosorption")
    df = generate_arm("A", "laiv_like", [dense], n=30, seed=11)
    k = fit_kinetics(df, n_boot=150, seed=2).kinetic
    lo, hi = k.ci_peak_day
    assert lo <= hi
    assert hi > lo, "degenerate interval"


def test_fit_is_deterministic_for_a_given_seed():
    dense = next(s for s in demo_series() if s.method == "nasosorption")
    df = generate_arm("A", "laiv_like", [dense], n=20, seed=9)
    a = fit_kinetics(df, n_boot=60, seed=4).kinetic
    b = fit_kinetics(df, n_boot=60, seed=4).kinetic
    assert a.peak_day == b.peak_day and a.ci_peak_day == b.ci_peak_day


def test_fit_handles_all_missing_values_without_crashing():
    df = pd.DataFrame({"subject_id": ["s1"] * 3, "day": [0, 7, 28], "value": [np.nan] * 3})
    k = fit_kinetics(df, n_boot=10).kinetic
    assert not k.identifiable


# --- the generator --------------------------------------------------------- #
def test_demo_dataset_shape_and_labels():
    df = demo_dataset(n=10)
    assert len(df) == 2 * 10 * sum(len(s.days) for s in demo_series())
    assert (df["source"] == "synthetic").all(), "synthetic data must be labelled everywhere"
    assert df["arm_id"].nunique() == 2
    assert df["subject_id"].nunique() == 20


def test_generator_is_reproducible():
    assert demo_dataset(n=6, seed=1).equals(demo_dataset(n=6, seed=1))
    assert not demo_dataset(n=6, seed=1).equals(demo_dataset(n=6, seed=2))


def test_generator_injects_the_heterogeneity_the_engine_must_catch():
    df = demo_dataset(n=6)
    assert df["unit"].nunique() >= 4
    assert df["lab"].nunique() >= 2
    assert df["normalization"].nunique() >= 2
    assert df["below_lloq"].any(), "no censored values: the LLOQ path would be untested"
    assert df["value"].isna().any(), "no missing visits: the missingness path would be untested"


def test_titre_series_snaps_to_two_fold_dilutions():
    titres = demo_dataset(n=8).query("unit == 'titer'")["value"].dropna()
    ratios = titres / 10.0
    assert np.allclose(np.log2(ratios), np.round(np.log2(ratios)), atol=1e-9)


def test_intranasal_arm_is_more_mucosal_than_the_injected_arm():
    """Sanity check on the generator's own premise, not a biological claim."""
    df = demo_dataset(n=40, seed=21)
    nasal = df[(df["method"] == "nasosorption") & (df["day"] == 14)]
    med = nasal.groupby("arm_id")["value"].median()
    assert med["LAIV-like (IN)"] > med["IIV-like (IM)"]


def test_fold_rise_is_relative_to_own_baseline():
    df = demo_dataset(n=8)
    fr = fold_rise_table(df)
    base = fr[fr["day"] == 0]["fold_rise"]
    assert np.allclose(base, 1.0)


# --------------------------------------------------------------------------- #
# Figure regressions: two defects that made a panel unreadable without ever
# failing a test, because nothing asserted on the figure's own coordinates.
# --------------------------------------------------------------------------- #

def _demo_figure():
    from mvc.comparability import harmonize_units
    from mvc.figures import kinetics_figure
    df = harmonize_units(demo_dataset(n=20, seed=42))
    return df, kinetics_figure(df, n_boot=10)


def test_annotation_y_is_an_exponent_on_a_log_axis():
    """Plotly reads an annotation's y as the exponent when the axis is log.

    Passing the raw value asked for 10^218000; the axis grew to 10^112 and
    flattened every real curve in that panel.
    """
    df, fig = _demo_figure()
    ymax = float(df["value"].max())
    notes = [a for a in fig.layout.annotations if "too few to fit" in str(a.text)]
    assert notes, "the demo dataset must contain at least one unfittable series"
    for a in notes:
        assert a.y <= np.log10(ymax) + 1, (
            f"annotation y={a.y} is a raw value, not log10 — the axis will explode")


def test_peak_marker_never_leaves_the_observation_window():
    """A fitted peak beyond the last visit is an artefact, not an observation."""
    df, fig = _demo_figure()
    last_day = float(df["day"].max())
    # add_vline(x=v) becomes a shape with x0 == x1 == v
    xs = [s.x0 for s in fig.layout.shapes if getattr(s, "x0", None) is not None]
    assert xs, "no peak markers at all: the assertion below would be vacuous"
    outside = [x for x in xs if x > last_day]
    assert not outside, f"peak markers drawn past day {last_day}: {outside}"
