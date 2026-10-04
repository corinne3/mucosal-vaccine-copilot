"""Comparability engine (heart of objective 4, reused by objectives 2 and 3).

Question answered: *can value A and value B be put side by side?*

The engine is a list of small, explicit rules. Each rule looks at the two
measurement contexts and may raise a `Flag`. The worst severity wins:

    comparable            -> no flag
    conditional           -> comparable with caveats (show, but annotate)
    not_comparable        -> never plot on the same absolute axis

Why rules and not ML: the brief asks for *transparent* flagging. A reviewer
must be able to read why two curves were separated. Each flag carries a code,
a human message and a suggested remedy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from itertools import combinations
from typing import Callable, Iterable, Optional

import pandas as pd

from .schema import (
    UNIT_CONVERSIONS,
    Compartment,
    MeasurementContext,
    Normalization,
    SamplingMethod,
)


class Level(IntEnum):
    comparable = 0
    conditional = 1
    not_comparable = 2


@dataclass(frozen=True)
class Flag:
    code: str
    level: Level
    message: str
    remedy: str = ""


@dataclass
class ComparabilityResult:
    level: Level
    flags: list[Flag] = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.level.name

    def as_dict(self) -> dict:
        return {
            "level": self.label,
            "flags": [
                {"code": f.code, "level": f.level.name, "message": f.message, "remedy": f.remedy}
                for f in self.flags
            ],
        }


Rule = Callable[[MeasurementContext, MeasurementContext, dict], Optional[Flag]]
RULES: list[Rule] = []


def rule(fn: Rule) -> Rule:
    RULES.append(fn)
    return fn


# --------------------------------------------------------------------------- #
# Rules — ordered from the most to the least structural
# --------------------------------------------------------------------------- #
@rule
def different_compartment(a, b, opts):
    if a.compartment != b.compartment:
        return Flag(
            "COMPARTMENT",
            Level.not_comparable,
            f"Different compartments ({a.compartment.value} vs {b.compartment.value}): "
            "mucosal and systemic responses are compartmentalised, absolute values are not on the same scale.",
            "Compare kinetics *shape* only (fold-rise over own baseline, time to peak, half-life).",
        )


@rule
def mucosal_sampling_method(a, b, opts):
    if a.compartment != b.compartment or not a.compartment.is_mucosal:
        return None
    if a.method == b.method:
        return None
    both_normalized = a.normalization == b.normalization == Normalization.total_iga
    if both_normalized:
        return Flag(
            "SAMPLING_METHOD",
            Level.conditional,
            f"Different mucosal sampling methods ({a.method.value} vs {b.method.value}) "
            "but both normalised to total IgA: dilution largely cancelled.",
            "Keep the caveat in the legend; check recovery efficiency of each device.",
        )
    return Flag(
        "SAMPLING_METHOD",
        Level.not_comparable,
        f"Different mucosal sampling methods ({a.method.value} vs {b.method.value}) without "
        "common normalisation: dilution factors differ (lavage dilutes, absorptive strips do not).",
        "Normalise specific IgA to total IgA (or use fold-rise) before comparing.",
    )


@rule
def different_assay(a, b, opts):
    if a.assay != b.assay:
        return Flag(
            "ASSAY",
            Level.not_comparable,
            f"Different assays ({a.assay.value} vs {b.assay.value}): binding and functional readouts "
            "measure different things.",
            "Compare within assay type only.",
        )


@rule
def different_isotype(a, b, opts):
    if a.isotype != b.isotype:
        iga = {"IgA", "sIgA"}
        if {a.isotype.value, b.isotype.value} <= iga:
            return Flag(
                "ISOTYPE",
                Level.conditional,
                "IgA vs secretory IgA: sIgA is a subset of IgA (needs secretory-component detection).",
                "State the detection reagent; do not pool.",
            )
        return Flag(
            "ISOTYPE",
            Level.not_comparable,
            f"Different isotypes ({a.isotype.value} vs {b.isotype.value}).",
            "Compare within isotype.",
        )


@rule
def different_normalization(a, b, opts):
    if a.normalization != b.normalization and a.compartment == b.compartment:
        if a.compartment.is_mucosal and a.method != b.method:
            return None  # already handled by mucosal_sampling_method
        return Flag(
            "NORMALIZATION",
            Level.not_comparable,
            f"Different normalisations ({a.normalization.value} vs {b.normalization.value}).",
            "Re-express both values with the same normalisation.",
        )


@rule
def different_unit(a, b, opts):
    if a.unit == b.unit:
        return None
    if (a.unit, b.unit) in UNIT_CONVERSIONS:
        return Flag(
            "UNIT_CONVERTIBLE",
            Level.conditional,
            f"Units differ but are convertible ({a.unit.value} -> {b.unit.value}).",
            "Convert before plotting (done automatically by `harmonize_units`).",
        )
    arbitrary = "au_ml" in (a.unit.value, b.unit.value)
    return Flag(
        "UNIT",
        Level.not_comparable,
        f"Incompatible units ({a.unit.value} vs {b.unit.value})"
        + (" — arbitrary units are lab-specific" if arbitrary else "") + ".",
        "Use a common reference standard (e.g. WHO BAU) or compare fold-rise.",
    )


@rule
def different_antigen(a, b, opts):
    if a.antigen != b.antigen and "unspecified" not in (a.antigen, b.antigen):
        return Flag(
            "ANTIGEN",
            Level.conditional,
            f"Different antigens ({a.antigen} vs {b.antigen}).",
            "Interpret as cross-reactivity, not as the same response.",
        )


@rule
def different_lab(a, b, opts):
    if a.lab != b.lab:
        return Flag(
            "LAB",
            Level.conditional,
            f"Different laboratories ({a.lab} vs {b.lab}): inter-lab bias is common for mucosal assays.",
            "Use bridging samples or a shared reference standard.",
        )


@rule
def digitized_source(a, b, opts):
    if "digitized_from_figure" in (a.source, b.source):
        return Flag(
            "DIGITIZED",
            Level.conditional,
            "At least one value was digitised from a published figure (approximate).",
            "Treat as indicative; prefer tabulated data.",
        )


@rule
def mixed_synthetic(a, b, opts):
    if (a.source == "synthetic") != (b.source == "synthetic"):
        return Flag(
            "SYNTHETIC_MIX",
            Level.not_comparable,
            "Synthetic values compared with real measurements.",
            "Never mix synthetic and real data on the same evidence plot.",
        )


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def compare(a: MeasurementContext, b: MeasurementContext, **opts) -> ComparabilityResult:
    flags = [f for r in RULES if (f := r(a, b, opts)) is not None]
    level = max((f.level for f in flags), default=Level.comparable)
    return ComparabilityResult(level=level, flags=flags)


CONTEXT_COLUMNS = [
    "compartment", "method", "isotype", "assay", "unit", "normalization", "antigen", "lab", "source",
]


def context_from_row(row: pd.Series | dict) -> MeasurementContext:
    get = row.get
    return MeasurementContext(
        compartment=Compartment(get("compartment")),
        method=SamplingMethod(get("method")),
        isotype=get("isotype"),
        assay=get("assay"),
        unit=get("unit"),
        normalization=get("normalization", "none") or "none",
        antigen=get("antigen", "unspecified") or "unspecified",
        lab=get("lab", "lab_1") or "lab_1",
        lloq=get("lloq"),
        source=get("source", "measured") or "measured",
    )


def series_key(row: pd.Series | dict) -> str:
    """Stable identifier of a measurement series (one context)."""
    return " | ".join(str(row.get(c, "")) for c in CONTEXT_COLUMNS if c not in ("antigen",))


def comparability_matrix(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[tuple[str, str], ComparabilityResult]]:
    """Pairwise comparability between all distinct measurement series of a long table."""
    series = (
        df.assign(_key=df.apply(series_key, axis=1))
        .drop_duplicates("_key")
        .set_index("_key")
    )
    keys = list(series.index)
    mat = pd.DataFrame(Level.comparable.name, index=keys, columns=keys)
    details: dict[tuple[str, str], ComparabilityResult] = {}
    for k1, k2 in combinations(keys, 2):
        res = compare(context_from_row(series.loc[k1]), context_from_row(series.loc[k2]))
        mat.loc[k1, k2] = mat.loc[k2, k1] = res.label
        details[(k1, k2)] = res
    return mat, details


def audit_table(df: pd.DataFrame, min_timepoints: int = 4) -> pd.DataFrame:
    """Row/series-level data-quality flags (independent of pairwise comparison)."""
    out = []
    df = df.assign(_key=df.apply(series_key, axis=1))
    for key, g in df.groupby("_key"):
        n_tp = g["day"].nunique()
        n_subj = g["subject_id"].nunique()
        n_lloq = int(g.get("below_lloq", pd.Series(False, index=g.index)).fillna(False).sum())
        n_missing = int(g["value"].isna().sum())
        flags = []
        if n_tp < min_timepoints:
            flags.append(f"only {n_tp} timepoints: kinetic parameters not identifiable")
        if n_lloq / max(len(g), 1) > 0.2:
            flags.append(f"{n_lloq} values below LLOQ (>20%): censoring biases means downwards")
        if n_missing / max(len(g), 1) > 0.15:
            flags.append(f"{n_missing} missing values (>15%)")
        if (g["unit"] == "au_ml").any():
            flags.append("arbitrary units: lab-specific scale")
        if 0 not in set(g["day"].round()):
            flags.append("no baseline (day 0): fold-rise impossible")
        out.append({
            "series": key, "n_subjects": n_subj, "n_timepoints": n_tp,
            "below_lloq": n_lloq, "missing": n_missing,
            "flags": flags, "uncertainty": "high" if len(flags) >= 2 else ("medium" if flags else "low"),
        })
    return pd.DataFrame(out)


def harmonize_units(df: pd.DataFrame, target: str = "ug_ml") -> pd.DataFrame:
    """Convert convertible mass-concentration units in place (returns a copy)."""
    df = df.copy()
    from .schema import Unit

    for (src, dst), factor in UNIT_CONVERSIONS.items():
        if dst.value == target:
            mask = df["unit"] == src.value
            df.loc[mask, "value"] = df.loc[mask, "value"] * factor
            df.loc[mask, "unit"] = Unit(target).value
    return df


def explain(result: ComparabilityResult) -> str:
    if not result.flags:
        return "Comparable: same compartment, method, assay, isotype, unit, normalisation and lab."
    lines = [f"Verdict: {result.label}"]
    for f in sorted(result.flags, key=lambda f: -f.level):
        lines.append(f"- [{f.level.name}] {f.code}: {f.message}" + (f" → {f.remedy}" if f.remedy else ""))
    return "\n".join(lines)


def iter_rules() -> Iterable[str]:
    for r in RULES:
        yield f"{r.__name__}: {(r.__doc__ or '').strip()}"
