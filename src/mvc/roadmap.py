"""Objective 6 — 90-day validation roadmap, generated FROM the run's own results.

The point: a roadmap written by hand is a wish list. This one is derived from
what the pipeline actually found — each unsupported option, each failed
self-check, each unidentifiable kinetic fit and each non-comparable pair becomes
a task with an owner and an acceptance criterion.

The IP section deliberately states facts and questions only, never conclusions:
IP strategy is a lawyer's call (the HackLab has a patent attorney mentor).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from .comparability import Level, audit_table, comparability_matrix
from .kinetics import fit_kinetics
from .strategy.agent import AgentState


@dataclass
class Task:
    task_id: str
    title: str
    owner: str
    week: int
    acceptance: str
    origin: str = ""
    priority: str = "medium"  # high | medium | low

    @property
    def month(self) -> int:
        return min(3, (self.week - 1) // 4 + 1)


@dataclass
class Roadmap:
    tasks: list[Task] = field(default_factory=list)
    ip_facts: list[str] = field(default_factory=list)
    ip_questions: list[str] = field(default_factory=list)
    assumptions_to_test: list[str] = field(default_factory=list)

    def by_month(self) -> dict[int, list[Task]]:
        out: dict[int, list[Task]] = {1: [], 2: [], 3: []}
        for t in sorted(self.tasks, key=lambda t: (t.week, t.task_id)):
            out[t.month].append(t)
        return out


def build_roadmap(state: AgentState, data: pd.DataFrame | None = None) -> Roadmap:
    rm = Roadmap()
    n = 0

    def add(title, owner, week, acceptance, origin, priority="medium"):
        nonlocal n
        n += 1
        rm.tasks.append(Task(f"T{n:02d}", title, owner, week, acceptance, origin, priority))

    p = state.proposal
    assert p is not None, "run the agent first"

    # --- 1. every unsupported option becomes a validation task --------------
    for o in p.options:
        if o.assumption:
            add(f"Validate or reject: {o.choice}", "domain expert", 1,
                "Expert signs off, or the option is removed from the plan.",
                f"option {o.option_id} has no supporting evidence", "high")
            rm.assumptions_to_test.append(f"{o.option_id}: {o.choice}")

    # --- 2. every open question gets an owner -------------------------------
    owner_for = [
        (("sample size", "power", "statistic"), "biostatistician"),
        (("device", "nasosorption", "lavage", "assay", "lab", "standard"), "lab lead"),
        (("endpoint", "regulatory", "primary"), "clinical trial expert"),
        (("immunity", "correlate", "immunolog"), "mucosal immunologist"),
    ]
    for q in p.open_questions:
        owner = "project lead"
        for words, who in owner_for:
            if any(w in q.lower() for w in words):
                owner = who
                break
        add(f"Resolve: {q[:110]}", owner, 2, "Written answer recorded in the decision log.",
            "open question from the strategy run")

    # --- 3. failed self-checks ---------------------------------------------
    if state.critique and not state.critique.passed:
        for issue in state.critique.issues:
            add(f"Fix: {issue[:110]}", "project lead", 1,
                "Self-check passes on the next pipeline run.", "agent self-check failure", "high")

    # --- 4. evidence base hardening ----------------------------------------
    to_verify = [s.study_id for s in state.eb.studies if s.level.value == "to_verify"]
    if to_verify:
        add(f"Retrieve and verify {len(to_verify)} placeholder studies ({', '.join(to_verify[:3])}…)",
            "data engineer", 1,
            "Every study carries a verified abstract; no 'to_verify' entry remains citable.",
            "evidence base contains unverified placeholders", "high")
    add("Second reviewer re-checks every quote against its source", "domain expert", 3,
        "100% of quotes confirmed verbatim; disagreements logged.",
        "anti-hallucination control needs a human in the loop", "high")
    add("Expand the evidence base to 30+ studies with the same verification gate", "data engineer", 4,
        "Coverage report shows no empty cell for the planned platform x method combinations.",
        "current base is a seed, not a systematic review")

    # --- 5. data-driven tasks from the actual dataset ------------------------
    if data is not None and len(data):
        mat, details = comparability_matrix(data)
        n_bad = sum(1 for v in details.values() if v.level == Level.not_comparable)
        if n_bad:
            add(f"Reduce the {n_bad} non-comparable series pairs (harmonise device, unit, lab)",
                "lab lead", 5,
                "Comparability matrix shows no 'not_comparable' pair within a planned comparison.",
                "comparability matrix on the demo dataset", "high")
        audit = audit_table(data)
        thin = audit[audit["n_timepoints"] < 4]
        if len(thin):
            add(f"Add timepoints to {len(thin)} thin series so kinetics become identifiable",
                "clinical trial expert", 5,
                "Every series used for a kinetic claim has >= 4 timepoints including a late one.",
                "data-quality audit")
        if audit["below_lloq"].sum():
            add("Pre-specify the LLOQ handling (censored-data method, not LLOQ/2 imputation)",
                "biostatistician", 6,
                "Statistical analysis plan names the censoring method and the sensitivity analysis.",
                f"{int(audit['below_lloq'].sum())} values below LLOQ in the demo dataset")
        for key, g in data.assign(_k=data.apply(lambda r: f"{r['compartment']}/{r['method']}", axis=1)).groupby("_k"):
            fit = fit_kinetics(g, n_boot=60)
            k = fit.kinetic
            if k.ci_half_life and k.half_life_days and k.ci_half_life[1] > 5 * k.half_life_days:
                add(f"Add a late visit for {key}: half-life not constrained", "clinical trial expert", 6,
                    "Bootstrap CI of the half-life narrows below a factor 3.",
                    "kinetic fit on the demo dataset")

    # --- 6. engineering & reproducibility -----------------------------------
    add("Replace synthetic demo data with the first real dataset, keeping the synthetic suite as tests",
        "data engineer", 7, "Pipeline runs on real data; synthetic tests still green in CI.",
        "demo currently runs on synthetic data", "high")
    add("Freeze a reproducible environment (pinned versions, seeded runs, data manifest with hashes)",
        "data engineer", 8, "Two machines produce byte-identical outputs from the same inputs.",
        "reproducibility requirement for regulated contexts")
    add("Run the retrieval and extraction eval suite on an expanded gold set", "data engineer", 9,
        "Recall@3 and quote-verification rate reported with a documented threshold.",
        "eval harness exists but the gold set is small")
    add("Write the user-facing limits document (what the tool must never be used for)", "project lead", 10,
        "One page, reviewed by the domain expert, shipped with the tool.",
        "scope control")
    add("Dry-run the whole flow with the domain experts on one realistic scenario", "project lead", 11,
        "Experts can follow every recommendation back to its source without help.",
        "transparency is the product's main claim", "high")
    add("Decide go / no-go on a validation study, with the decision log attached", "project lead", 12,
        "Written decision, with the list of assumptions still untested.", "end of the 90 days", "high")

    # --- IP: facts and questions only ---------------------------------------
    rm.ip_facts = [
        "The code in this repository is the author's own work, written on public and synthetic data only.",
        "The evidence base cites public literature; abstracts are quoted, not redistributed in full.",
        "Europe PMC and ClinicalTrials.gov content is used under their respective terms; each record keeps its identifier.",
        "No partner data, no confidential document and no third-party dataset is included.",
        "Open-weight models are called locally; no data leaves the machine at inference time.",
        "Any work produced inside a company-sponsored track belongs under that track's own agreement, "
        "which is why this repository is kept separate from it.",
    ]
    rm.ip_questions = [
        "Which parts, if any, are patentable rather than simply publishable? (patent attorney)",
        "Does an open-source licence (and which one) serve the project better than keeping it closed?",
        "If a partner's data is used later, what agreement must be in place first?",
        "Are the licence terms of each model and dataset compatible with the intended use?",
        "Who owns contributions made by other participants, and is that written down?",
    ]
    return rm


def to_markdown(rm: Roadmap, start: date | None = None, title: str = "90-day validation & IP roadmap") -> str:
    start = start or date.today()
    lines = [f"# {title}", "",
             f"_Generated from the pipeline's own results on {start.isoformat()}. "
             "Every task traces back to a gap the run detected._", "",
             "IP section states facts and open questions only — IP strategy is a qualified lawyer's call.", ""]
    for month, tasks in rm.by_month().items():
        if not tasks:
            continue
        lines += [f"## Month {month} (weeks {(month - 1) * 4 + 1}–{month * 4})", "",
                  "| id | task | owner | week of | priority | acceptance criterion | why |",
                  "|---|---|---|---|---|---|---|"]
        for t in tasks:
            when = (start + timedelta(weeks=t.week - 1)).isoformat()
            lines.append(f"| {t.task_id} | {t.title} | {t.owner} | {when} | {t.priority} | "
                         f"{t.acceptance} | {t.origin} |")
        lines.append("")
    if rm.assumptions_to_test:
        lines += ["## Assumptions with no supporting evidence (test or drop)", ""]
        lines += [f"- {a}" for a in rm.assumptions_to_test] + [""]
    lines += ["## IP — established facts", ""] + [f"- {f}" for f in rm.ip_facts]
    lines += ["", "## IP — open questions for counsel", ""] + [f"- {q}" for q in rm.ip_questions] + [""]
    return "\n".join(lines)


def to_dataframe(rm: Roadmap) -> pd.DataFrame:
    return pd.DataFrame([{
        "id": t.task_id, "month": t.month, "week": t.week, "task": t.title, "owner": t.owner,
        "priority": t.priority, "acceptance": t.acceptance, "origin": t.origin,
    } for t in sorted(rm.tasks, key=lambda t: (t.week, t.task_id))])
