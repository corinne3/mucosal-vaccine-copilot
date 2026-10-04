"""Table 1 of the workshop report, run through the comparability engine.

Everything else in this project is either synthetic (`synthetic.py`) or text
(`evidence/`). This module is the one place where *real* measurement metadata
enters: six consortia, each describing how it samples the airway and which
assays it runs, transcribed from a published table.

It answers a question the table itself poses but does not answer: **if these
six trials each produce an antibody number, which of those numbers may be put
side by side?**

The answer has two halves, and the second is the useful one:

1. What the table *does* record — compartment, sampling device, assay family —
   is already enough to rule a great many pairs out. Nasosorption against BAL
   is not a comparison, it is two different organs sampled two different ways.
2. What the table does *not* record — unit, normalisation, assay floor,
   antigen, laboratory — is exactly what decides the remaining pairs. Five of
   the ten fields the comparability engine needs are simply absent from the
   published description.

So the engine cannot return "comparable" for any cross-consortium pair, and
that is not a defect in the engine. It is a measurement of the table: a
published methods table, as currently written, does not carry enough metadata
for a reader to know whether two trials' numbers can be compared. That is a
concrete, checkable finding, and it names the five fields a harmonised
reporting standard would have to add.

Nothing here is a judgement on the science or the consortia. The engine sees
metadata only — it never sees a measured value, and these trials have not
published any.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .comparability import ComparabilityResult, Level, compare
from .evidence.store import ROOT
from .schema import (
    METHOD_COMPARTMENT,
    AssayType,
    Isotype,
    MeasurementContext,
    Normalization,
    SamplingMethod,
    Unit,
)

TABLE1_PATH = ROOT / "data" / "evidence" / "consortia_table1.json"

#: Placeholders for the five fields Table 1 does not record. They are *not*
#: guesses: `au_ml` is the unit a binding assay reports when no unit is given,
#: `none` is the absence of a normalisation statement, and the laboratory is
#: the consortium itself. Each one is listed in `MISSING_FIELDS` so that every
#: downstream verdict can say which of its reasons rest on absent metadata.
MISSING_FIELDS = ("unit", "normalization", "lloq", "antigen", "lab")


@dataclass
class ConsortiumSeries:
    """One (consortium x sampling method x assay) triple from Table 1."""

    consortium: str
    registration: str | None
    method_verbatim: str
    assay_verbatim: str
    context: MeasurementContext
    #: Fields whose value in `context` is a placeholder, not a transcription.
    unrecorded: tuple[str, ...] = field(default_factory=lambda: MISSING_FIELDS)

    @property
    def label(self) -> str:
        # The isotype belongs in the label. Without it, "IgG/IgA titres" — one
        # cell that expands into two series — produced two identically named
        # rows, which read as a duplication bug rather than as the two distinct
        # measurements they are.
        return (f"{self.consortium} · {self.context.method.value} · "
                f"{self.context.isotype.value} · {self.context.assay.value}")


@dataclass
class Unmodelled:
    """A Table 1 cell this project deliberately does not represent, and why."""

    consortium: str
    kind: str          # "sampling" or "assay"
    verbatim: str
    reason: str


@dataclass
class Table1:
    series: list[ConsortiumSeries]
    unmodelled: list[Unmodelled]
    raw: dict

    @property
    def consortia(self) -> list[str]:
        return [c["name"] for c in self.raw["consortia"]]


def load_table1(path: Path | str = TABLE1_PATH) -> Table1:
    """Expand Table 1 into one measurement context per (consortium, method, assay).

    A consortium is not a measurement. VAXXAIR samples three upper-airway
    sites and runs two assay families, so it does not have "a" measurement
    context — it has six. Flattening a consortium to one row would hide
    exactly the heterogeneity the project exists to surface, so the expansion
    is the cross product, and every cell that cannot be expanded is recorded
    in `unmodelled` rather than dropped.
    """
    raw = json.loads(Path(path).read_text())
    m_map: dict = raw["method_mapping"]
    m_notes: dict = raw.get("method_mapping_notes", {})
    a_map: dict = raw["assay_mapping"]

    series: list[ConsortiumSeries] = []
    unmodelled: list[Unmodelled] = []

    for c in raw["consortia"]:
        name, nct = c["name"], c.get("registration")
        methods = c["upper_airway_verbatim"] + c["lower_airway_verbatim"]

        resolved_methods: list[tuple[str, SamplingMethod]] = []
        for verbatim in methods:
            if verbatim not in m_map:
                raise KeyError(f"Table 1 cell not in method_mapping: {verbatim!r}")
            target = m_map[verbatim]
            if target is None:
                unmodelled.append(Unmodelled(
                    name, "sampling", verbatim,
                    m_notes.get(verbatim, "not an immune measurement")))
                continue
            resolved_methods.append((verbatim, SamplingMethod(target)))

        resolved_assays: list[tuple[str, AssayType, list[Isotype]]] = []
        for verbatim in c["assays_verbatim"]:
            if verbatim not in a_map:
                raise KeyError(f"Table 1 cell not in assay_mapping: {verbatim!r}")
            spec = a_map[verbatim]
            if spec is None:
                unmodelled.append(Unmodelled(
                    name, "assay", verbatim,
                    "measures cells, transcripts or virus, not an antibody quantity"))
                continue
            # "IgG/IgA titres" is two measurements written as one cell. They are
            # different isotypes in different compartments and are never
            # interchangeable, so the cell expands into two series.
            isos = ([Isotype.IgG, Isotype.IgA] if spec["isotype"] == "split_IgG_IgA"
                    else [Isotype(spec["isotype"])])
            resolved_assays.append((verbatim, AssayType(spec["assay"]), isos))

        for mv, method in resolved_methods:
            for av, assay, isos in resolved_assays:
                for iso in isos:
                    series.append(ConsortiumSeries(
                        consortium=name, registration=nct,
                        method_verbatim=mv, assay_verbatim=av,
                        context=MeasurementContext(
                            compartment=METHOD_COMPARTMENT[method],
                            method=method, isotype=iso, assay=assay,
                            # the five placeholders, declared in `unrecorded`
                            unit=Unit.au_ml, normalization=Normalization.none,
                            antigen="unspecified", lab=name, lloq=None,
                            source="rosenheim2026_workshop Table 1",
                        )))

    if not series:
        raise ValueError("Table 1 produced no measurement series — check the mappings")
    return Table1(series=series, unmodelled=unmodelled, raw=raw)


def cross_consortium_matrix(t1: Table1) -> tuple[pd.DataFrame, dict]:
    """Compare every Table 1 series against every other.

    Returns a square verdict frame and the detail per pair. Only pairs from
    *different* consortia are interesting — a consortium comparing its own
    series is a within-trial question it can already answer.
    """
    labels = [s.label for s in t1.series]
    mat = pd.DataFrame("", index=labels, columns=labels, dtype=object)
    details: dict[tuple[str, str], ComparabilityResult] = {}
    for i, a in enumerate(t1.series):
        for j, b in enumerate(t1.series):
            if i == j:
                mat.iloc[i, j] = "self"
                continue
            r = compare(a.context, b.context)
            mat.iloc[i, j] = r.label
            details[(labels[i], labels[j])] = r
    return mat, details


def cross_consortium_summary(t1: Table1) -> pd.DataFrame:
    """One row per ordered pair of distinct consortia: can anything be compared?"""
    rows = []
    for a in t1.series:
        for b in t1.series:
            if a.consortium >= b.consortium:
                continue
            r = compare(a.context, b.context)
            rows.append({
                "consortium_a": a.consortium, "consortium_b": b.consortium,
                "series_a": a.label, "series_b": b.label,
                "verdict": r.label,
                "level": max((f.level for f in r.flags), default=Level.comparable).name,
                "blocking_reasons": "; ".join(
                    f.code for f in r.flags if f.level == Level.not_comparable) or "—",
                # The question worth asking, and the one that took two wrong
                # definitions to reach.
                #
                # It is NOT "did a unit/normalisation flag fire?" — none ever
                # does, because the table records no units and every series
                # therefore carries the same placeholder. The engine sees them
                # agree, which is an artefact of the placeholder, not a fact.
                #
                # Nor is it "is a laboratory difference involved?" — two
                # consortia are two laboratories, which the table does record.
                #
                # It is this: the fields Table 1 *does* record all agree, so
                # nothing recorded stands in the way any more, and whether
                # these two numbers may actually be compared is decided
                # entirely by the five fields the table does not record. These
                # are the pairs where the missing metadata is load-bearing —
                # the only pairs for which a reporting standard would change
                # the answer.
                "decided_by_unrecorded_metadata": r.label != "not_comparable",
            })
    return pd.DataFrame(rows)


def metadata_gap_report(t1: Table1) -> pd.DataFrame:
    """What Table 1 would have to add, per field, for a verdict to be possible.

    This is the module's actual deliverable for a partner: not "your trials are
    incomparable", which would be both rude and unfounded, but "here are the
    five columns your methods table does not have, and here is what each one
    decides".
    """
    what_it_decides = {
        "unit": "Whether two numbers are on the same scale at all. ug/mL and AU/mL "
                "are not convertible without the assay's own calibration.",
        "normalization": "Whether sampling dilution has been cancelled. Specific IgA "
                         "normalised to total IgA is comparable across devices; raw is not.",
        "lloq": "Which values are measurements and which are floors. Without it, "
                "censored points are silently treated as real.",
        "antigen": "What the antibody binds. Two 'IgA titres' against different "
                   "strains answer different questions.",
        "lab": "Which site actually runs the assay. The table names the consortium, "
               "not the laboratory, and a consortium may be several sites. Same "
               "assay, different site, routinely differs by a factor of two or more.",
    }
    missing = t1.raw["fields_the_table_does_not_record"]
    for f in missing:
        if f not in what_it_decides:
            raise KeyError(
                f"{f!r} is listed as unrecorded in the data file but no explanation "
                "is given for what it decides — a gap report that cannot say why a "
                "field matters is not a finding, it is a complaint.")
    return pd.DataFrame([
        {"field": f, "recorded_in_table_1": False, "what_it_decides": what_it_decides[f]}
        for f in missing
    ])


def shared_methods(t1: Table1) -> pd.DataFrame:
    """Which sampling methods several consortia already have in common.

    The optimistic half of the finding: convergence on a device is real and
    worth naming, even while the reporting metadata is missing.
    """
    rows = []
    seen: dict[SamplingMethod, set[str]] = {}
    for s in t1.series:
        seen.setdefault(s.context.method, set()).add(s.consortium)
    for method, names in sorted(seen.items(), key=lambda kv: (-len(kv[1]), kv[0].value)):
        rows.append({
            "method": method.value,
            "compartment": METHOD_COMPARTMENT[method].value,
            "n_consortia": len(names),
            "consortia": ", ".join(sorted(names)),
        })
    return pd.DataFrame(rows)
