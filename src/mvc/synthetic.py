"""Synthetic data generator (objective 5).

!! All numbers produced here are SYNTHETIC. Parameter values are *illustrative
assumptions* chosen to reproduce qualitative patterns reported in the
literature (see docs/objectifs/05_demo.md):
  * intranasal live-attenuated vaccines -> mucosal IgA response, weaker serum response
  * intramuscular inactivated vaccines  -> strong serum IgG, little mucosal IgA
  * mucosal and systemic responses are compartmentalised (weakly correlated)
  * mucosal IgA rises earlier and wanes faster than serum IgG
  * not every participant responds (responder fraction < 1)
They are NOT estimates of any real vaccine and must never be presented as such.

The generator also *injects* the measurement heterogeneity that the comparability
engine must catch: lavage dilution, arbitrary units, inter-lab bias, LLOQ
censoring, missing visits, too-sparse sampling.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .kinetics import bateman


@dataclass
class ResponseSpec:
    """Population distribution of one kinetic response (Bateman parameters)."""

    baseline: float
    fold_peak: float          # median peak / baseline among responders
    peak_day: float
    half_life: float
    responder_rate: float = 1.0
    between_cv: float = 0.5   # between-subject variability (log-normal)


@dataclass
class SeriesSpec:
    """One measured series = response x measurement context."""

    response: str             # key into profile responses
    method: str
    compartment: str
    isotype: str
    assay: str
    unit: str
    days: list[int]
    normalization: str = "none"
    lab: str = "lab_1"
    lab_bias: float = 1.0     # multiplicative bias of the lab
    assay_cv: float = 0.25
    lloq: float | None = None   # assay floor: values below it are censored, not measured
    dilution: tuple[float, float] | None = None  # log-normal (median, cv) of sample dilution
    unit_scale: float = 1.0
    antigen: str = "HA"
    titer: bool = False
    missing_rate: float = 0.05


# Illustrative profiles — qualitative, NOT fitted to any trial.
PROFILES: dict[str, dict[str, ResponseSpec]] = {
    "laiv_like": {
        "nasal_iga": ResponseSpec(baseline=1.0, fold_peak=4.0, peak_day=14, half_life=60, responder_rate=0.6),
        "serum_igg": ResponseSpec(baseline=20.0, fold_peak=1.6, peak_day=28, half_life=150, responder_rate=0.35),
        "saliva_iga": ResponseSpec(baseline=1.0, fold_peak=1.8, peak_day=12, half_life=45, responder_rate=0.4),
    },
    "iiv_im_like": {
        "nasal_iga": ResponseSpec(baseline=1.0, fold_peak=1.3, peak_day=21, half_life=60, responder_rate=0.15),
        "serum_igg": ResponseSpec(baseline=20.0, fold_peak=6.0, peak_day=24, half_life=150, responder_rate=0.85),
        "saliva_iga": ResponseSpec(baseline=1.0, fold_peak=1.2, peak_day=21, half_life=45, responder_rate=0.1),
    },
    "adv_in_like": {
        "nasal_iga": ResponseSpec(baseline=1.0, fold_peak=2.5, peak_day=14, half_life=50, responder_rate=0.45),
        "serum_igg": ResponseSpec(baseline=10.0, fold_peak=3.0, peak_day=28, half_life=120, responder_rate=0.6),
        "saliva_iga": ResponseSpec(baseline=1.0, fold_peak=1.5, peak_day=14, half_life=40, responder_rate=0.3),
    },
}


def bateman_from_shape(peak_day: float, half_life: float, baseline: float, fold_peak: float):
    """Invert (peak_day, half_life, fold) -> Bateman (A, ka, ke)."""
    ke = np.log(2) / half_life
    # solve ln(ka/ke)/(ka-ke) = peak_day for ka > ke (monotone decreasing in ka)
    lo, hi = ke * 1.0001, 50.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if np.log(mid / ke) / (mid - ke) > peak_day:
            lo = mid
        else:
            hi = mid
    ka = 0.5 * (lo + hi)
    shape_at_peak = np.exp(-ke * peak_day) - np.exp(-ka * peak_day)
    A = baseline * (fold_peak - 1.0) / shape_at_peak
    return A, ka, ke


def _subject_params(spec: ResponseSpec, n: int, rng: np.random.Generator):
    sd = np.sqrt(np.log(1 + spec.between_cv ** 2))
    base = spec.baseline * rng.lognormal(0, sd, n)
    responder = rng.random(n) < spec.responder_rate
    fold = np.where(responder, spec.fold_peak * rng.lognormal(0, sd, n), 1.0 + 0.1 * rng.random(n))
    fold = np.maximum(fold, 1.0001)
    peak = np.clip(spec.peak_day * rng.lognormal(0, 0.2, n), 3, None)
    hl = spec.half_life * rng.lognormal(0, 0.3, n)
    return base, fold, peak, hl, responder


def _to_titer(x: np.ndarray, start: float = 10.0) -> np.ndarray:
    """Snap to two-fold dilution series (10, 20, 40, ...)."""
    steps = np.round(np.log2(np.clip(x, start / 2, None) / start))
    return start * 2.0 ** np.clip(steps, -1, None)


def generate_arm(
    arm_id: str,
    profile: str,
    series: list[SeriesSpec],
    n: int = 30,
    seed: int = 0,
    subject_prefix: str | None = None,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    prof = PROFILES[profile]
    rows = []
    # subject-level true kinetics are shared across the series measuring the same response
    truth = {k: _subject_params(spec, n, rng) for k, spec in prof.items()}
    prefix = subject_prefix or arm_id
    for s in series:
        base, fold, peak, hl, responder = truth[s.response]
        for i in range(n):
            A, ka, ke = bateman_from_shape(peak[i], hl[i], base[i], fold[i])
            days = np.array(s.days, dtype=float)
            true = bateman(days, base[i], A, ka, ke)
            dil = np.ones_like(true)
            if s.dilution:
                med, cv = s.dilution
                dil = med * rng.lognormal(0, np.sqrt(np.log(1 + cv ** 2)), len(days))
            noise = rng.lognormal(0, np.sqrt(np.log(1 + s.assay_cv ** 2)), len(days))
            obs = true * dil * noise * s.lab_bias * s.unit_scale
            total_iga = None
            if s.normalization == "total_iga":
                # total IgA diluted by the same factor -> ratio cancels dilution
                total = 200.0 * rng.lognormal(0, 0.3, len(days)) * dil
                total_iga = total
                obs = obs / total
            if s.titer:
                obs = _to_titer(obs)
            for j, d in enumerate(days):
                val = float(obs[j])
                below = s.lloq is not None and val < s.lloq
                if below:
                    val = s.lloq / 2.0  # conventional LLOQ/2 imputation
                if rng.random() < s.missing_rate and d != 0:
                    val = np.nan
                rows.append({
                    "subject_id": f"{prefix}-{i + 1:03d}", "arm_id": arm_id, "day": float(d),
                    "value": val, "compartment": s.compartment, "method": s.method,
                    "isotype": s.isotype, "assay": s.assay, "unit": s.unit,
                    "normalization": s.normalization, "antigen": s.antigen, "lab": s.lab,
                    "source": "synthetic", "lloq": s.lloq, "below_lloq": bool(below),
                    "responder": bool(responder[i]),
                    "total_iga": None if total_iga is None else float(total_iga[j]),
                })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Ready-made demo dataset: deliberately heterogeneous
# --------------------------------------------------------------------------- #
DENSE = [0, 3, 7, 10, 14, 21, 28, 56, 90, 180]
STANDARD = [0, 7, 14, 28, 90, 180]
SPARSE = [0, 28, 180]


def demo_series() -> list[SeriesSpec]:
    return [
        # nasal IgA by lavage, raw ELISA AU (dilution NOT corrected)
        SeriesSpec("nasal_iga", "nasal_wash", "nasal", "IgA", "elisa_binding", "au_ml", STANDARD,
                   lab="lab_1", dilution=(0.1, 0.6), unit_scale=100, lloq=4.0),
        # nasal IgA by nasosorption, normalised to total IgA, other lab
        SeriesSpec("nasal_iga", "nasosorption", "nasal", "sIgA", "elisa_binding", "ratio", DENSE,
                   normalization="total_iga", lab="lab_2", lab_bias=1.3, unit_scale=1),
        # saliva IgA (mucosal but not nasal)
        SeriesSpec("saliva_iga", "saliva", "oral", "IgA", "elisa_binding", "au_ml", STANDARD,
                   lab="lab_1", unit_scale=50, lloq=15.0),
        # serum IgG binding in ug/mL
        SeriesSpec("serum_igg", "serum", "serum", "IgG", "elisa_binding", "ug_ml", STANDARD, lab="lab_1"),
        # same serum response reported by lab 2 in ng/mL (convertible)
        SeriesSpec("serum_igg", "serum", "serum", "IgG", "elisa_binding", "ng_ml", SPARSE,
                   lab="lab_2", unit_scale=1000, lab_bias=0.8),
        # serum HAI titre (functional, two-fold dilutions)
        SeriesSpec("serum_igg", "serum", "serum", "total", "hai", "titer", STANDARD,
                   lab="lab_1", unit_scale=2.0, titer=True),
    ]


def demo_dataset(n: int = 30, seed: int = 42) -> pd.DataFrame:
    series = demo_series()
    a = generate_arm("LAIV-like (IN)", "laiv_like", series, n=n, seed=seed, subject_prefix="A")
    b = generate_arm("IIV-like (IM)", "iiv_im_like", series, n=n, seed=seed + 1, subject_prefix="B")
    return pd.concat([a, b], ignore_index=True)


def save_demo(path: str = "data/synthetic/demo_kinetics.csv", n: int = 30, seed: int = 42) -> str:
    df = demo_dataset(n=n, seed=seed)
    df.to_csv(path, index=False)
    return path
