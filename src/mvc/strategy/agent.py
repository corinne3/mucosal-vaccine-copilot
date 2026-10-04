"""Agentic layer over the rule engine.

Why an agent at all: the rule engine needs a *structured* `TrialScenario`, but a
user types free text ("compare a nasal flu vaccine to the injected one in adults,
6 visits max, I care about durability"). The agent's job is the messy edges:
parse the text, decide which tools to call, retrieve supporting evidence,
check its own output, and write the briefing.

Graph (a small state machine, inspected and testable):

    parse ──> propose ──> retrieve ──> critique ──┬──> report
                 ▲                                │
                 └──────── revise (once) ─────────┘

`critique` is the interesting node: it re-reads the proposal and fails it on
objective grounds (unsupported options above a threshold, a cited quote that is
not in its source, a visit budget violated). A failed critique loops once with
a tightened scenario, then reports regardless, with the critique attached.

Runs on a hand-rolled executor by default (zero dependency, works offline).
If `langgraph` is installed, `build_langgraph()` returns the same graph as a
LangGraph `StateGraph`, so you can show either in the demo.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .. import llm
from ..evidence.extract import quote_in_source
from ..evidence.search import HybridSearcher
from ..evidence.store import chunks as make_chunks
from ..schema import EvidenceBase, Platform, Population, Route, TrialScenario, Vaccine
from .rules import StrategyProposal, propose, to_markdown

# --------------------------------------------------------------------------- #
# Scenario parsing: LLM with constrained JSON, deterministic keyword fallback
# --------------------------------------------------------------------------- #
SCENARIO_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "pathogen": {"type": "string"},
        "vaccine_name": {"type": "string"},
        "platform": {"type": "string", "enum": [p.value for p in Platform]},
        "route": {"type": "string", "enum": [r.value for r in Route]},
        "comparator_route": {"type": "string", "enum": [r.value for r in Route] + ["none"]},
        "comparator_platform": {"type": "string", "enum": [p.value for p in Platform] + ["none"]},
        "n_participants": {"type": "integer"},
        "follow_up_days": {"type": "integer"},
        "max_visits": {"type": "integer"},
        "age_min": {"type": "integer"},
        "age_max": {"type": "integer"},
        "pediatric": {"type": "boolean"},
        "prior_immunity": {"type": "string", "enum": ["naive", "low", "high", "unknown"]},
        "questions": {"type": "array", "items": {
            "type": "string",
            "enum": ["peak", "durability", "mucosal_vs_systemic", "correlate_of_protection"]}},
    },
    "required": ["name", "pathogen", "platform", "route", "n_participants",
                 "follow_up_days", "max_visits", "questions"],
}

PARSE_SYSTEM = (
    "Convert the user's description of a vaccine trial scenario into the JSON schema. "
    "Use only what the text states; for anything absent use these defaults: "
    "n_participants 30, follow_up_days 180, max_visits 6, prior_immunity unknown, "
    "questions ['peak','durability']. Never invent a pathogen."
)

KEYWORDS = {
    "route": [(Route.intranasal, ("intranasal", "nasal", "nose", "spray", "intranasale")),
              (Route.inhaled, ("inhaled", "aerosol")),
              (Route.oral, ("oral",)),
              (Route.intramuscular, ("intramuscular", "injected", "injection", " im ", "parenteral"))],
    "platform": [(Platform.live_attenuated, ("live attenuated", "laiv", "live-attenuated", "flumist")),
                 (Platform.adenovirus_vector, ("adenovir", "chad", "vector")),
                 (Platform.mrna, ("mrna",)),
                 (Platform.inactivated, ("inactivated", "iiv", "killed")),
                 (Platform.protein_subunit, ("subunit", "recombinant protein"))],
}
PATHOGENS = [("influenza", ("influenza", "flu", "grippe", "h1n1", "h3n2")),
             ("SARS-CoV-2", ("sars-cov-2", "covid", "coronavirus")),
             ("RSV", ("rsv", "respiratory syncytial"))]
QUESTIONS = [("durability", ("durab", "waning", "persist", "6 month", "long term", "longevity")),
             ("mucosal_vs_systemic", ("mucosal vs", "versus systemic", "compare compartment", "mucosal and systemic")),
             ("correlate_of_protection", ("correlate", "protection", "challenge")),
             ("peak", ("peak", "kinetic", "when"))]


def _first(text: str, table: list[tuple[Any, tuple[str, ...]]], default=None):
    low = f" {text.lower()} "
    for value, words in table:
        if any(w in low for w in words):
            return value
    return default


def parse_scenario_rules(text: str) -> TrialScenario:
    """Deterministic fallback parser — always available, never hallucinates."""
    import re

    low = text.lower()
    route = _first(text, KEYWORDS["route"], Route.intranasal)
    platform = _first(text, KEYWORDS["platform"], Platform.other)
    pathogen = _first(text, PATHOGENS, "unspecified")
    qs = [q for q, words in QUESTIONS if any(w in f" {low} " for w in words)] or ["peak", "durability"]

    def num(pattern: str, default: int) -> int:
        m = re.search(pattern, low)
        return int(m.group(1)) if m else default

    # "40 healthy adults" silently became the default 30, because the original
    # pattern allowed only whitespace between the number and the noun, and
    # "children" was not a noun it knew. A parser that quietly substitutes a
    # default for a number the user typed is worse than one that fails loudly:
    # the demo showed "30" beside a sentence saying "40" and nothing flagged it.
    # Up to two intervening adjectives are now allowed, and the noun list covers
    # the populations this domain actually enrols.
    _WHO = (r"participants?|subjects?|volunteers?|adults?|people|persons?|patients?"
            r"|children|infants|toddlers|sujets?|enfants?|nourrissons?|adultes?")
    # The intervening words must not be time or visit units, or "180 days in
    # adults" reads as a cohort of 180 — the number is the follow-up, and the
    # noun it belongs to is three words away. Widening a pattern creates false
    # positives as reliably as it fixes false negatives; both need a test.
    _NOT_TIME = r"(?!\s*(?:days?|weeks?|months?|years?|visits?|jours?|semaines?|mois|ans?)\b)"
    n = num(rf"(\d+){_NOT_TIME}\s+(?:[a-zé]+\s+){{0,2}}(?:{_WHO})\b", 30)
    visits = num(r"(\d+)\s*(?:visits|visites|samples|prélèvements|timepoints)", 6)
    follow = num(r"(\d+)\s*(?:days?|jours?)\s*(?:of\s*)?follow", 180)
    if months := re.search(r"(\d+)\s*months?\s*(?:of\s*)?(?:follow|suivi)", low):
        follow = int(months.group(1)) * 30
    comparator = None
    if any(w in low for w in ("compare", "versus", " vs ", "comparator", "comparaison")):
        other = Route.intramuscular if route != Route.intramuscular else Route.intranasal
        comparator = Vaccine(name=f"comparator ({other.value})", pathogen=pathogen,
                             platform=Platform.inactivated, route=other)
    pediatric = any(w in low for w in ("child", "children", "paediatric", "pediatric", "infant", "enfant"))
    return TrialScenario(
        name=text.strip()[:70] or "unnamed scenario",
        vaccine=Vaccine(name=f"{platform.value} ({route.value})", pathogen=pathogen,
                        platform=platform, route=route),
        comparator=comparator,
        population=Population(age_min=2 if pediatric else 18, age_max=17 if pediatric else 64,
                              pediatric=pediatric, prior_immunity="unknown"),
        n_participants=n, max_visits=max(2, visits), follow_up_days=follow, questions=qs,
        notes="parsed by deterministic keyword rules",
    )


def parse_scenario_llm(text: str) -> TrialScenario:
    d = llm.chat_json(f"USER DESCRIPTION:\n{text}", schema=SCENARIO_SCHEMA, system=PARSE_SYSTEM)
    vac = Vaccine(name=d.get("vaccine_name") or d["platform"], pathogen=d["pathogen"],
                  platform=Platform(d["platform"]), route=Route(d["route"]))
    comp = None
    cr, cp = d.get("comparator_route", "none"), d.get("comparator_platform", "none")
    if cr not in ("none", None) and cp not in ("none", None):
        comp = Vaccine(name=f"comparator ({cr})", pathogen=d["pathogen"],
                       platform=Platform(cp), route=Route(cr))
    return TrialScenario(
        name=d["name"], vaccine=vac, comparator=comp,
        population=Population(age_min=d.get("age_min", 18), age_max=d.get("age_max", 64),
                              pediatric=d.get("pediatric", False),
                              prior_immunity=d.get("prior_immunity", "unknown")),
        n_participants=d["n_participants"], follow_up_days=d["follow_up_days"],
        max_visits=max(2, d["max_visits"]), questions=d["questions"] or ["peak"],
        notes="parsed by local LLM",
    )


def parse_scenario(text: str, use_llm: bool | None = None) -> tuple[TrialScenario, str]:
    if use_llm is None:
        use_llm = llm.is_available(llm.LLM_MODEL)
    if use_llm:
        try:
            return parse_scenario_llm(text), "llm"
        except (llm.LLMUnavailable, ValueError, KeyError):
            pass
    return parse_scenario_rules(text), "rules"


# --------------------------------------------------------------------------- #
# Critique: objective self-checks on the agent's own output
# --------------------------------------------------------------------------- #
@dataclass
class Critique:
    passed: bool
    issues: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)


def critique(p: StrategyProposal, eb: EvidenceBase, max_assumption_share: float = 0.4) -> Critique:
    issues, checks = [], {}
    index = {f.finding_id: (s, f) for s in eb.studies for f in s.findings}

    share = 1.0 - p.coverage["share_backed"]
    checks["assumption_share_ok"] = share <= max_assumption_share
    if not checks["assumption_share_ok"]:
        issues.append(f"{share:.0%} of options have no supporting evidence (limit {max_assumption_share:.0%}).")

    bad = []
    for o in p.options:
        for e in o.evidence:
            hit = index.get(e.finding_id)
            if hit is None:
                bad.append(f"{e.finding_id} not in evidence base")
                continue
            study, _ = hit
            ok, score = quote_in_source(e.quote, study.source_text)
            if not ok:
                bad.append(f"{e.finding_id} quote not found in source (best match {score:.2f})")
    checks["quotes_verified"] = not bad
    issues += bad

    checks["budget_respected"] = len(p.sampling_days) <= p.scenario.max_visits
    if not checks["budget_respected"]:
        issues.append(f"{len(p.sampling_days)} visits proposed for a budget of {p.scenario.max_visits}.")

    checks["baseline_present"] = 0 in p.sampling_days
    if not checks["baseline_present"]:
        issues.append("No day-0 sample: fold-rise cannot be computed.")

    checks["within_followup"] = all(d <= p.scenario.follow_up_days for d in p.sampling_days)
    if not checks["within_followup"]:
        issues.append("A visit falls after the end of follow-up.")

    if "durability" in p.scenario.questions:
        checks["late_visit_for_durability"] = max(p.sampling_days or [0]) >= min(90, p.scenario.follow_up_days)
        if not checks["late_visit_for_durability"]:
            issues.append("Durability asked but no late visit: half-life will not be identifiable.")

    checks["experts_flagged"] = bool(p.open_questions)
    if not checks["experts_flagged"]:
        issues.append("No open question listed for the domain experts — suspicious for this kind of task.")

    return Critique(passed=not issues, issues=issues, checks=checks)


# --------------------------------------------------------------------------- #
# State and nodes
# --------------------------------------------------------------------------- #
@dataclass
class AgentState:
    text: str
    eb: EvidenceBase
    scenario: TrialScenario | None = None
    parser: str = ""
    proposal: StrategyProposal | None = None
    retrieved: list[dict] = field(default_factory=list)
    critique: Critique | None = None
    report: str = ""
    revisions: int = 0
    log: list[str] = field(default_factory=list)

    def note(self, msg: str) -> None:
        self.log.append(msg)


def node_parse(st: AgentState) -> str:
    st.scenario, st.parser = parse_scenario(st.text)
    st.note(f"parse: {st.parser} -> {st.scenario.vaccine.route.value} "
            f"{st.scenario.vaccine.platform.value}, {st.scenario.max_visits} visits, "
            f"questions={st.scenario.questions}")
    return "propose"


def node_propose(st: AgentState) -> str:
    assert st.scenario
    st.proposal = propose(st.scenario, st.eb)
    st.note(f"propose: {len(st.proposal.options)} options, visits {st.proposal.sampling_days}")
    return "retrieve"


def node_retrieve(st: AgentState) -> str:
    """Pull extra evidence for each open question — the part that benefits from search."""
    searcher = HybridSearcher(make_chunks(st.eb))
    st.retrieved = []
    for q in (st.proposal.open_questions if st.proposal else [])[:5]:
        hits = searcher.search(q, k=2, citable_only=True)
        st.retrieved.append({"question": q, "hits": [
            {"chunk_id": h.chunk.chunk_id, "study_id": h.chunk.study_id,
             "text": h.chunk.text, "score": round(h.score, 4)} for h in hits]})
    st.note(f"retrieve: {searcher.mode}, {sum(len(r['hits']) for r in st.retrieved)} supporting chunks")
    return "critique"


def node_critique(st: AgentState) -> str:
    assert st.proposal
    st.critique = critique(st.proposal, st.eb)
    st.note(f"critique: {'pass' if st.critique.passed else 'fail'} "
            f"({len(st.critique.issues)} issue(s))")
    if st.critique.passed or st.revisions >= 1:
        return "report"
    return "revise"


def node_revise(st: AgentState) -> str:
    """One bounded repair pass: fix what is mechanically fixable in the scenario."""
    assert st.scenario and st.critique
    st.revisions += 1
    c = st.critique.checks
    fixes = []
    if not c.get("budget_respected", True):
        st.scenario = st.scenario.model_copy(update={"max_visits": st.scenario.max_visits + 1})
        fixes.append("raised visit budget by 1")
    if not c.get("late_visit_for_durability", True):
        # a late visit needs both a long enough follow-up AND a free slot in the budget
        st.scenario = st.scenario.model_copy(update={
            "follow_up_days": max(st.scenario.follow_up_days, 180),
            "max_visits": max(st.scenario.max_visits, len(st.proposal.sampling_days) + 1)
            if st.proposal else st.scenario.max_visits,
        })
        fixes.append("extended follow-up and freed one visit slot for a late sample")
    st.note(f"revise: {', '.join(fixes) if fixes else 'nothing mechanically fixable'}")
    return "propose"


def node_report(st: AgentState) -> str:
    assert st.proposal and st.critique
    md = to_markdown(st.proposal)
    lines = ["", "## Self-check", ""]
    for k, v in st.critique.checks.items():
        lines.append(f"- {'PASS' if v else 'FAIL'} — {k}")
    if st.critique.issues:
        lines += ["", "**Unresolved issues**", ""] + [f"- {i}" for i in st.critique.issues]
    if st.retrieved:
        lines += ["", "## Evidence retrieved for the open questions", ""]
        for r in st.retrieved:
            lines.append(f"**{r['question']}**")
            for h in r["hits"]:
                lines.append(f"- `{h['chunk_id']}` {h['text'][:260]}")
            lines.append("")
    lines += ["", "## Agent trace", ""] + [f"{i + 1}. {m}" for i, m in enumerate(st.log)]
    st.report = md + "\n".join(lines) + "\n"
    return "END"


NODES: dict[str, Callable[[AgentState], str]] = {
    "parse": node_parse, "propose": node_propose, "retrieve": node_retrieve,
    "critique": node_critique, "revise": node_revise, "report": node_report,
}


def run_agent(text: str, eb: EvidenceBase, max_steps: int = 12) -> AgentState:
    """Hand-rolled executor: no dependency, deterministic, fully traced."""
    st = AgentState(text=text, eb=eb)
    node = "parse"
    for _ in range(max_steps):
        if node == "END":
            return st
        node = NODES[node](st)
    st.note("executor: step limit reached")
    if not st.report and st.proposal:
        node_report(st)
    return st


# --------------------------------------------------------------------------- #
# Same graph, LangGraph flavour (optional dependency)
# --------------------------------------------------------------------------- #
def build_langgraph():
    """Returns a compiled LangGraph app with identical semantics, or raises
    ImportError if langgraph is not installed."""
    from langgraph.graph import END, StateGraph

    def wrap(fn):
        def inner(state: dict) -> dict:
            st: AgentState = state["st"]
            state["next"] = fn(st)
            return state
        return inner

    g = StateGraph(dict)
    for name, fn in NODES.items():
        g.add_node(name, wrap(fn))
    g.set_entry_point("parse")
    g.add_edge("parse", "propose")
    g.add_edge("propose", "retrieve")
    g.add_edge("retrieve", "critique")
    g.add_conditional_edges("critique", lambda s: s["next"], {"revise": "revise", "report": "report"})
    g.add_edge("revise", "propose")
    g.add_edge("report", END)
    return g.compile()


def trace_json(st: AgentState) -> str:
    return json.dumps({
        "input": st.text, "parser": st.parser,
        "scenario": st.scenario.model_dump(mode="json") if st.scenario else None,
        "visits": st.proposal.sampling_days if st.proposal else [],
        "coverage": st.proposal.coverage if st.proposal else {},
        "critique": {"passed": st.critique.passed, "checks": st.critique.checks,
                     "issues": st.critique.issues} if st.critique else None,
        "revisions": st.revisions, "log": st.log,
    }, indent=2)


# --------------------------------------------------------------------------- #
# Rules against LLM, side by side
# --------------------------------------------------------------------------- #
#: The fields worth diffing. Deliberately not every field of TrialScenario:
#: `notes` records which parser ran and would differ by construction, which
#: would make every comparison look like a disagreement.
_COMPARED_FIELDS = (
    "pathogen", "platform", "route", "comparator_route",
    "n_participants", "max_visits", "follow_up_days", "pediatric", "questions",
)


def _flatten(s: TrialScenario) -> dict[str, object]:
    return {
        "pathogen": s.vaccine.pathogen,
        "platform": s.vaccine.platform.value,
        "route": s.vaccine.route.value,
        "comparator_route": s.comparator.route.value if s.comparator else "—",
        "n_participants": s.n_participants,
        "max_visits": s.max_visits,
        "follow_up_days": s.follow_up_days,
        "pediatric": s.population.pediatric,
        "questions": ", ".join(sorted(s.questions)),
    }


def compare_parsers(text: str) -> dict:
    """Parse one scenario both ways and report where the two disagree.

    This exists because "we have an LLM" and "the LLM helps" are different
    claims, and only the second is worth making. Running both parsers on the
    same sentence and showing the diff turns the question into something a
    reader can check: on plain phrasing the keyword rules match the model
    field for field, and the model earns its place only on sentences the rules
    were never written for — negation, an unusual word order, a number spelled
    out, a pathogen the keyword list does not contain.

    Returns a dict with both flattened scenarios, the differing fields, and
    whether the LLM path actually ran. If no text model is pulled, `llm_ran`
    is False and the comparison degrades to "rules only" rather than failing.
    """
    rules = parse_scenario_rules(text)
    out: dict = {
        "rules": _flatten(rules),
        "llm": None,
        "llm_ran": False,
        "differences": [],
        "model": llm.LLM_MODEL,
        "error": None,
    }
    if not llm.is_available(llm.LLM_MODEL):
        out["error"] = f"no text model pulled ({llm.LLM_MODEL}) — rules only"
        return out
    try:
        model_scenario = parse_scenario_llm(text)
    except (llm.LLMUnavailable, ValueError, KeyError, TypeError) as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out

    out["llm"] = _flatten(model_scenario)
    out["llm_ran"] = True
    out["differences"] = [
        f for f in _COMPARED_FIELDS if out["rules"].get(f) != out["llm"].get(f)
    ]
    return out
