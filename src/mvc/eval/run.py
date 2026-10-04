"""Eval suite — four measurable claims, each with a threshold that can fail CI.

1. retrieval     — recall@k and MRR against a hand-judged gold set
2. extraction    — quote-verification rate on synthetically corrupted findings
                   (a hallucination detector must catch injected fakes)
3. kinetics      — parameter recovery on synthetic data where truth is known,
                   plus calibration of the bootstrap intervals
4. comparability — the rule engine on a labelled table of context pairs

Nothing here needs an LLM or the network, so it runs in the train and in CI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..comparability import MeasurementContext, compare
from ..evidence.extract import quote_in_source
from ..evidence.search import HybridSearcher
from ..evidence.store import ROOT, chunks, load
from ..kinetics import fit_kinetics, peak_time
from ..synthetic import PROFILES, bateman_from_shape, demo_series, generate_arm

GOLD = ROOT / "data" / "eval" / "retrieval_gold.json"

THRESHOLDS = {
    "retrieval_recall@3": 0.70,
    # recall@5 is reported alongside @3 because @3 is partly bounded by
    # construction: a query with 4 relevant findings can never score above
    # 0.75 at k=3, so growing the gold set depresses @3 for reasons that have
    # nothing to do with retrieval quality.
    "retrieval_recall@5": 0.80,
    "retrieval_mrr": 0.60,
    "extraction_fake_detection": 1.00,
    "extraction_true_acceptance": 0.95,
    "kinetics_peak_rel_error": 0.35,   # upper bound
    "kinetics_ci_coverage": 0.70,      # lower bound (nominal 95%, tolerant)
    "comparability_accuracy": 1.00,
}


@dataclass
class Metric:
    name: str
    value: float
    threshold: float
    higher_is_better: bool = True
    detail: str = ""
    gating: bool = True
    """Whether this metric can fail the build.

    Non-gating metrics are measured and reported but never block, because they
    depend on data that is not under version control (the auto-extracted
    corpus, which every machine downloads differently). A gate whose input
    differs per machine is not a gate.
    """

    @property
    def passed(self) -> bool:
        if not self.gating:
            return True
        return self.value >= self.threshold if self.higher_is_better else self.value <= self.threshold


@dataclass
class Report:
    metrics: list[Metric] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(m.passed for m in self.metrics if m.gating)

    def __str__(self) -> str:
        w = max((len(m.name) for m in self.metrics), default=10)
        lines = [f"{'metric'.ljust(w)}  value   threshold  status"]
        for m in self.metrics:
            arrow = ">=" if m.higher_is_better else "<="
            status = "PASS" if m.passed else "FAIL"
            if not m.gating:
                status = "info"
                arrow = "  "
            lines.append(f"{m.name.ljust(w)}  {m.value:6.3f}  {arrow}{m.threshold:6.3f}  "
                         f"{status}" + (f"   {m.detail}" if m.detail else ""))
        lines.append(f"\nOVERALL: {'PASS' if self.passed else 'FAIL'}")
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps({"passed": self.passed, "metrics": [
            {"name": m.name, "value": m.value, "threshold": m.threshold, "passed": m.passed,
             "gating": m.gating, "detail": m.detail} for m in self.metrics]}, indent=2)


# --------------------------------------------------------------------------- #
# 1. retrieval
# --------------------------------------------------------------------------- #
def eval_retrieval(ks: tuple[int, ...] = (3, 5)) -> list[Metric]:
    """Measure retrieval twice, over two different corpora, for one reason.

    The gating numbers run on the CURATED base alone (`seed_evidence.json`,
    which is in git). The auto-extracted base is in .gitignore, so every
    machine has a different one — mine had none, this user's had 56 extra
    studies, CI would have none again. Gating on that made the threshold
    meaningless: three machines, three numbers, and a 0.863 that could not be
    compared with a 0.799.

    The merged corpus is still measured, and reported as `info`, because it is
    what the system actually serves. It just cannot be allowed to fail a build.
    Its gold set is also incomplete by construction: the 111 auto-extracted
    findings were never hand-judged, so a genuinely relevant one counts as an
    error.
    """
    gold = json.loads(Path(GOLD).read_text(encoding="utf-8"))["cases"]
    out: list[Metric] = []

    def measure(eb, k: int) -> tuple[float, int, list[float], str]:
        searcher = HybridSearcher(chunks(eb))
        recalls, rrs, misses = [], [], 0
        for case in gold:
            ids = [h.chunk.chunk_id for h in searcher.search(case["query"], k=k, citable_only=True)]
            rel = set(case["relevant"])
            found = rel & set(ids)
            recalls.append(len(found) / len(rel))
            rank = next((i + 1 for i, cid in enumerate(ids) if cid in rel), None)
            rrs.append(1 / rank if rank else 0.0)
            misses += not found
        return float(np.mean(recalls)), misses, rrs, searcher.mode

    curated = load(include_extracted=False)
    rrs_curated: list[float] = []
    for k in ks:
        recall, misses, rrs, mode = measure(curated, k)
        if k == ks[0]:
            rrs_curated = rrs
        out.append(Metric(f"retrieval_recall@{k}", recall, THRESHOLDS[f"retrieval_recall@{k}"],
                          detail=f"{misses}/{len(gold)} queries with no hit · curated base"))
    out.append(Metric("retrieval_mrr", float(np.mean(rrs_curated)), THRESHOLDS["retrieval_mrr"],
                      detail=f"mode: {mode}"))

    merged = load(include_extracted=True)
    if len(merged.studies) > len(curated.studies):
        extra = len(merged.studies) - len(curated.studies)
        recall5, misses, rrs, _ = measure(merged, 5)
        out.append(Metric("retrieval_recall@5_merged", recall5, THRESHOLDS["retrieval_recall@5"],
                          detail=f"+{extra} auto-extracted studies, gold set incomplete for them",
                          gating=False))
        out.append(Metric("retrieval_mrr_merged", float(np.mean(rrs)), THRESHOLDS["retrieval_mrr"],
                          detail="informational only", gating=False))
    return out


# --------------------------------------------------------------------------- #
# 2. extraction / anti-hallucination
# --------------------------------------------------------------------------- #
FAKE_MUTATIONS = [
    lambda q: q.replace("mucosal", "systemic").replace("nasal", "serum"),
    lambda q: q + " and this effect was statistically significant in all subgroups",
    lambda q: "In a randomised controlled trial, " + q.lower().replace("the", "a"),
    lambda q: q.replace("low", "high").replace("weaker", "stronger").replace("not", ""),
    lambda q: " ".join(reversed(q.split())),
]


def eval_extraction() -> list[Metric]:
    """Gate on the curated base: its findings are hand-written, so accepting
    them is a real test. The auto-extracted findings are verbatim sentences by
    construction, so they cannot fail — counting them inflates the number
    without measuring anything."""
    eb = load(include_extracted=False)
    true_ok, true_n, fake_caught, fake_n = 0, 0, 0, 0
    for s in eb.studies:
        if not s.source_text:
            continue
        for f in s.findings:
            true_n += 1
            ok, _ = quote_in_source(f.quote, s.source_text)
            true_ok += ok
            for mut in FAKE_MUTATIONS:
                fake = mut(f.quote)
                if fake.strip() == f.quote.strip():
                    continue
                fake_n += 1
                bad, _ = quote_in_source(fake, s.source_text)
                fake_caught += not bad
    return [
        Metric("extraction_true_acceptance", true_ok / max(true_n, 1),
               THRESHOLDS["extraction_true_acceptance"], detail=f"{true_ok}/{true_n} real quotes accepted"),
        Metric("extraction_fake_detection", fake_caught / max(fake_n, 1),
               THRESHOLDS["extraction_fake_detection"], detail=f"{fake_caught}/{fake_n} corrupted quotes rejected"),
    ]


# --------------------------------------------------------------------------- #
# 3. kinetics parameter recovery + CI calibration
# --------------------------------------------------------------------------- #
def eval_kinetics(n_rep: int = 8, n_subj: int = 40, n_boot: int = 120) -> list[Metric]:
    """Ground truth is known because we generate it: fit the dense, clean series
    and compare the recovered peak day with the population truth."""
    dense = next(s for s in demo_series() if s.method == "nasosorption")
    errors, covered = [], []
    for rep in range(n_rep):
        df = generate_arm("eval", "laiv_like", [dense], n=n_subj, seed=100 + rep)
        spec = PROFILES["laiv_like"]["nasal_iga"]
        _, ka, ke = bateman_from_shape(spec.peak_day, spec.half_life, spec.baseline, spec.fold_peak)
        truth = peak_time(ka, ke)
        fit = fit_kinetics(df, n_boot=n_boot, seed=rep)
        k = fit.kinetic
        if not k.identifiable or not np.isfinite(k.peak_day):
            continue
        errors.append(abs(k.peak_day - truth) / truth)
        if k.ci_peak_day:
            covered.append(k.ci_peak_day[0] <= truth <= k.ci_peak_day[1])
    return [
        Metric("kinetics_peak_rel_error", float(np.mean(errors)) if errors else 1.0,
               THRESHOLDS["kinetics_peak_rel_error"], higher_is_better=False,
               detail=f"{len(errors)} fits, population peak day {PROFILES['laiv_like']['nasal_iga'].peak_day}"),
        Metric("kinetics_ci_coverage", float(np.mean(covered)) if covered else 0.0,
               THRESHOLDS["kinetics_ci_coverage"], detail=f"{sum(covered)}/{len(covered)} CIs contain the truth"),
    ]


# --------------------------------------------------------------------------- #
# 4. comparability rules
# --------------------------------------------------------------------------- #
def _ctx(**kw) -> MeasurementContext:
    base = dict(compartment="nasal", method="nasosorption", isotype="IgA", assay="elisa_binding",
                unit="au_ml", normalization="none", antigen="HA", lab="lab_1", source="measured")
    base.update(kw)
    return MeasurementContext.model_validate(base)


COMPARABILITY_CASES: list[tuple[MeasurementContext, MeasurementContext, str]] = [
    (_ctx(), _ctx(), "comparable"),
    (_ctx(), _ctx(compartment="serum", method="serum"), "not_comparable"),
    (_ctx(), _ctx(method="nasal_wash"), "not_comparable"),
    (_ctx(normalization="total_iga", unit="ratio"),
     _ctx(method="nasal_wash", normalization="total_iga", unit="ratio"), "conditional"),
    (_ctx(), _ctx(assay="neutralization"), "not_comparable"),
    (_ctx(), _ctx(isotype="IgG"), "not_comparable"),
    (_ctx(), _ctx(isotype="sIgA"), "conditional"),
    (_ctx(unit="ng_ml"), _ctx(unit="ug_ml"), "conditional"),
    (_ctx(), _ctx(lab="lab_2"), "conditional"),
    (_ctx(), _ctx(antigen="NA"), "conditional"),
    (_ctx(), _ctx(source="digitized_from_figure"), "conditional"),
    (_ctx(), _ctx(source="synthetic"), "not_comparable"),
    (_ctx(compartment="oral", method="saliva"), _ctx(), "not_comparable"),
]


def eval_comparability() -> list[Metric]:
    wrong = []
    for a, b, expected in COMPARABILITY_CASES:
        got = compare(a, b).label
        if got != expected:
            wrong.append(f"expected {expected}, got {got}")
    acc = 1 - len(wrong) / len(COMPARABILITY_CASES)
    return [Metric("comparability_accuracy", acc, THRESHOLDS["comparability_accuracy"],
                   detail="; ".join(wrong[:3]) or f"{len(COMPARABILITY_CASES)} labelled pairs")]


def run_all(verbose: bool = False, fast: bool = False) -> Report:
    rep = Report()
    rep.metrics += eval_retrieval()
    rep.metrics += eval_extraction()
    rep.metrics += eval_comparability()
    rep.metrics += eval_kinetics(n_rep=3 if fast else 8, n_boot=60 if fast else 120)
    if verbose:
        out = ROOT / "outputs"
        out.mkdir(exist_ok=True)
        (out / "eval_report.json").write_text(rep.to_json(), encoding="utf-8")
    return rep


if __name__ == "__main__":
    import sys

    r = run_all(verbose=True)
    print(r)
    sys.exit(0 if r.passed else 1)
