"""Antibody kinetic modelling (objective 4, and prior for objective 3's optimal design).

Model — the *Bateman function*, borrowed from pharmacokinetics (absorption /
elimination), here read as "production rise / decay":

    y(t) = b + A * (exp(-ke * τ) - exp(-ka * τ)),   τ = max(t - lag, 0),  ka > ke

    b    baseline level (pre-existing immunity)
    A    amplitude
    ka   rise rate   (1/day)
    ke   decay rate  (1/day) -> half-life = ln 2 / ke
    lag  delay before the response starts

Derived:  t_peak = lag + ln(ka/ke) / (ka - ke)

Noise on antibody data is multiplicative, so the fit minimises residuals on
log10 scale. Uncertainty is obtained by *subject-level bootstrap* (resample
participants, refit, take percentiles), which respects within-subject
correlation. If the design has too few timepoints, the function says so rather
than returning a falsely precise curve.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

from .schema import KineticParameters

LN2 = np.log(2.0)


def bateman(t, b, A, ka, ke, lag=0.0):
    t = np.asarray(t, dtype=float)
    tau = np.clip(t - lag, 0.0, None)
    return b + A * (np.exp(-ke * tau) - np.exp(-ka * tau))


def peak_time(ka: float, ke: float, lag: float = 0.0) -> float:
    if np.isclose(ka, ke):
        return lag + 1.0 / ka
    return lag + np.log(ka / ke) / (ka - ke)


@dataclass
class FitResult:
    params: dict[str, float]
    params_table: pd.DataFrame | None
    kinetic: KineticParameters
    curve_t: np.ndarray
    curve_y: np.ndarray
    band_lo: np.ndarray | None
    band_hi: np.ndarray | None


def _log_model(t, logb, logA, logka, logke):
    """Parameters on log scale keep them positive and well-conditioned."""
    y = bateman(t, np.exp(logb), np.exp(logA), np.exp(logka) + np.exp(logke), np.exp(logke))
    return np.log10(np.clip(y, 1e-12, None))


def _fit_once(t: np.ndarray, y: np.ndarray) -> np.ndarray | None:
    y = np.clip(y, 1e-9, None)
    b0 = max(np.median(y[t <= 1]) if (t <= 1).any() else np.min(y), 1e-6)
    A0 = max(np.max(y) - b0, b0 * 0.5)
    p0 = [np.log(b0), np.log(A0 * 1.5), np.log(0.15), np.log(0.03)]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            popt, _ = curve_fit(
                _log_model, t, np.log10(y), p0=p0, maxfev=20000,
                bounds=([-30, -30, np.log(1e-3), np.log(1e-4)], [30, 30, np.log(5.0), np.log(1.0)]),
            )
        return popt
    except (RuntimeError, ValueError):
        return None


def _to_natural(popt: np.ndarray) -> dict[str, float]:
    logb, logA, logka_extra, logke = popt
    ke = float(np.exp(logke))
    ka = float(np.exp(logka_extra) + ke)
    return {"b": float(np.exp(logb)), "A": float(np.exp(logA)), "ka": ka, "ke": ke}


def summarize(p: dict[str, float]) -> dict[str, float]:
    tp = peak_time(p["ka"], p["ke"])
    peak = float(bateman(tp, p["b"], p["A"], p["ka"], p["ke"]))
    return {
        "peak_day": tp,
        "peak_value": peak,
        "half_life_days": LN2 / p["ke"],
        "fold_rise": peak / p["b"] if p["b"] > 0 else np.nan,
    }


def fit_kinetics(
    df: pd.DataFrame,
    n_boot: int = 200,
    seed: int = 0,
    horizon: float | None = None,
    min_timepoints: int = 4,
) -> FitResult:
    """Fit one measurement series (columns: subject_id, day, value)."""
    d = df.dropna(subset=["value"])
    d = d[d["value"] > 0]
    t, y = d["day"].to_numpy(float), d["value"].to_numpy(float)
    n_tp, n_subj = int(np.unique(t).size), int(d["subject_id"].nunique())
    horizon = horizon or float(max(t.max() if t.size else 180, 30))
    grid = np.linspace(0, horizon, 200)
    notes: list[str] = []

    if n_tp < min_timepoints:
        notes.append(f"Only {n_tp} distinct timepoints (< {min_timepoints}): curve not identifiable.")
        med = d.groupby("day")["value"].median()
        kp = KineticParameters(
            baseline=float(med.iloc[0]) if len(med) else np.nan,
            peak_value=float(med.max()) if len(med) else np.nan,
            peak_day=float(med.idxmax()) if len(med) else np.nan,
            n_subjects=n_subj, n_timepoints=n_tp, identifiable=False, notes=notes,
        )
        return FitResult({}, None, kp, grid, np.full_like(grid, np.nan), None, None)

    popt = _fit_once(t, y)
    if popt is None:
        notes.append("Optimiser did not converge.")
        kp = KineticParameters(baseline=float(np.median(y)), peak_value=float(y.max()),
                               peak_day=float(t[np.argmax(y)]), n_subjects=n_subj,
                               n_timepoints=n_tp, identifiable=False, notes=notes)
        return FitResult({}, None, kp, grid, np.full_like(grid, np.nan), None, None)

    p = _to_natural(popt)
    s = summarize(p)
    curve = bateman(grid, p["b"], p["A"], p["ka"], p["ke"])

    # ---- subject-level bootstrap ------------------------------------------
    rng = np.random.default_rng(seed)
    subjects = d["subject_id"].unique()
    groups = {sid: g for sid, g in d.groupby("subject_id")}
    boots, curves = [], []
    for _ in range(n_boot):
        pick = rng.choice(subjects, size=len(subjects), replace=True)
        bd = pd.concat([groups[s_] for s_ in pick])
        bp = _fit_once(bd["day"].to_numpy(float), bd["value"].to_numpy(float))
        if bp is None:
            continue
        nat = _to_natural(bp)
        boots.append(summarize(nat))
        curves.append(bateman(grid, nat["b"], nat["A"], nat["ka"], nat["ke"]))

    lo = hi = None
    ci_peak = ci_hl = None
    table = None
    if len(boots) >= 20:
        bt = pd.DataFrame(boots)
        table = bt.quantile([0.025, 0.5, 0.975]).T
        ci_peak = (float(table.loc["peak_day", 0.025]), float(table.loc["peak_day", 0.975]))
        ci_hl = (float(table.loc["half_life_days", 0.025]), float(table.loc["half_life_days", 0.975]))
        arr = np.vstack(curves)
        lo, hi = np.percentile(arr, 2.5, axis=0), np.percentile(arr, 97.5, axis=0)
        if ci_hl[1] > 5 * max(s["half_life_days"], 1):
            notes.append("Half-life poorly constrained: not enough late timepoints.")
        if (ci_peak[1] - ci_peak[0]) > 21:
            notes.append("Peak day uncertain (95% CI wider than 3 weeks): add sampling around the peak.")
    else:
        notes.append("Bootstrap failed too often: uncertainty not quantified.")

    last_day = t.max()
    if s["half_life_days"] > 3 * last_day:
        notes.append("Half-life extrapolated far beyond last sample.")

    kp = KineticParameters(
        baseline=p["b"], peak_value=s["peak_value"], peak_day=s["peak_day"],
        half_life_days=s["half_life_days"], fold_rise=s["fold_rise"],
        ci_peak_day=ci_peak, ci_half_life=ci_hl, n_subjects=n_subj, n_timepoints=n_tp,
        identifiable=not any("not identifiable" in n for n in notes), notes=notes,
    )
    return FitResult(p, table, kp, grid, curve, lo, hi)


#: columns that, together with subject_id, identify one measurement series
_SERIES_COLS = ["compartment", "method", "isotype", "assay", "unit", "normalization", "lab"]


def fold_rise_table(df: pd.DataFrame) -> pd.DataFrame:
    """Per-subject fold-rise over own day-0 value: the scale on which
    compartments *can* be compared (shape, not absolute level).

    The baseline is taken per (subject, series), not per subject: one subject
    normally contributes several series (nasal and serum, two labs, two units),
    so a subject-only baseline would be ambiguous — and dividing a serum value
    by a nasal baseline is exactly the category error this project exists to
    prevent.
    """
    d = df.dropna(subset=["value"]).copy()
    keys = ["subject_id"] + [c for c in _SERIES_COLS if c in d.columns]
    base = (d[d["day"] == 0]
            .groupby(keys, dropna=False)["value"]
            .median()
            .rename("baseline")
            .reset_index())
    d = d.merge(base, on=keys, how="inner")
    d = d[d["baseline"] > 0]
    d["fold_rise"] = d["value"] / d["baseline"]
    return d
