"""Choosing sampling days with Bayesian D-optimal design (greedy).

Problem: a participant can only be sampled `max_visits` times. Which days give
the most information about the antibody kinetics (peak, half-life)?

Method (classic in pharmacometrics):
  * model  : log10 y(t; θ) — Bateman curve (see `mvc.kinetics`), θ = 4 log-params
  * information of a design D = {t1..tk}:  FIM(θ, D) = Jᵀ J / σ²,  J = ∂ log10 y / ∂θ at each t
  * D-optimality : maximise log det FIM  (shrinks the joint confidence ellipsoid)
  * Bayesian     : θ is uncertain -> average log det over prior draws of θ
  * greedy       : add the day that increases the criterion most, until budget

Mucosal and systemic responses are sampled at the SAME visits (paired design),
so the criterion is the sum over both responses.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..kinetics import _log_model
from ..schema import Platform, Route, TrialScenario
from ..synthetic import PROFILES, ResponseSpec, _subject_params, bateman_from_shape

CANDIDATE_DAYS = [0, 1, 3, 5, 7, 10, 14, 21, 28, 35, 42, 56, 90, 120, 180, 270, 365]


def profile_for(scn: TrialScenario) -> str:
    v = scn.vaccine
    if v.route in (Route.intranasal, Route.inhaled):
        return "adv_in_like" if v.platform == Platform.adenovirus_vector else "laiv_like"
    return "iiv_im_like"


def _theta_draws(spec: ResponseSpec, n: int, rng) -> np.ndarray:
    base, fold, peak, hl, responder = _subject_params(spec, n * 3, rng)
    keep = np.where(responder)[0][:n]
    if len(keep) < n:  # weak responders: still need draws
        keep = np.arange(n)
        fold = np.maximum(fold, 1.5)
    th = []
    for i in keep:
        A, ka, ke = bateman_from_shape(peak[i], hl[i], base[i], fold[i])
        th.append([np.log(base[i]), np.log(A), np.log(max(ka - ke, 1e-6)), np.log(ke)])
    return np.array(th)


def _jac(theta: np.ndarray, days: np.ndarray, h: float = 1e-4) -> np.ndarray:
    J = np.zeros((len(days), len(theta)))
    for j in range(len(theta)):
        d = np.zeros_like(theta)
        d[j] = h
        J[:, j] = (_log_model(days, *(theta + d)) - _log_model(days, *(theta - d))) / (2 * h)
    return J


def _criterion(jacs: list[np.ndarray], idx: list[int], sigma: float, ridge: float = 1e-6) -> float:
    vals = []
    for J in jacs:
        Js = J[idx]
        F = Js.T @ Js / sigma ** 2 + ridge * np.eye(J.shape[1])
        sign, logdet = np.linalg.slogdet(F)
        vals.append(logdet if sign > 0 else -1e9)
    return float(np.mean(vals))


@dataclass
class DesignResult:
    days: list[int]
    gains: list[tuple[int, float]]          # (day added, criterion after adding)
    criterion: float
    candidate_days: list[int]
    profile: str


def optimal_days(
    scn: TrialScenario,
    mandatory: list[int] | None = None,
    candidates: list[int] | None = None,
    n_draws: int = 40,
    sigma: float = 0.12,
    seed: int = 0,
    responses: tuple[str, ...] = ("nasal_iga", "serum_igg"),
) -> DesignResult:
    rng = np.random.default_rng(seed)
    cands = [d for d in (candidates or CANDIDATE_DAYS) if d <= scn.follow_up_days]
    mandatory = sorted(set(mandatory or [0]))
    cands = sorted(set(cands) | set(mandatory))
    days_arr = np.array(cands, dtype=float)
    prof = profile_for(scn)
    jacs = []
    for r in responses:
        for th in _theta_draws(PROFILES[prof][r], n_draws, rng):
            jacs.append(_jac(th, days_arr))
    chosen = [cands.index(d) for d in mandatory if d in cands]
    gains = []
    budget = scn.max_visits
    while len(chosen) < min(budget, len(cands)):
        best, best_val = None, -np.inf
        for i in range(len(cands)):
            if i in chosen:
                continue
            val = _criterion(jacs, chosen + [i], sigma)
            if val > best_val:
                best, best_val = i, val
        chosen.append(best)
        gains.append((cands[best], best_val))
    final = _criterion(jacs, chosen, sigma) if len(chosen) >= 4 else float("nan")
    return DesignResult(sorted(cands[i] for i in chosen), gains, final, cands, prof)


def compare_designs(scn: TrialScenario, designs: dict[str, list[int]], n_draws: int = 40,
                    sigma: float = 0.12, seed: int = 0) -> dict[str, float]:
    """Criterion of hand-written designs (e.g. 'standard' vs 'optimal') for the dashboard."""
    rng = np.random.default_rng(seed)
    all_days = sorted({d for ds in designs.values() for d in ds})
    arr = np.array(all_days, dtype=float)
    prof = profile_for(scn)
    jacs = [_jac(th, arr) for r in ("nasal_iga", "serum_igg") for th in _theta_draws(PROFILES[prof][r], n_draws, rng)]
    return {name: _criterion(jacs, [all_days.index(d) for d in ds], sigma) for name, ds in designs.items()}
