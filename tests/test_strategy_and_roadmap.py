"""Objectives 3 and 6 — rule engine, optimal design, agent, roadmap.

The theme: the tool must never present an assumption as evidence, and must never
silently drop a constraint.
"""

from __future__ import annotations

import pytest

from mvc.evidence.store import load
from mvc.roadmap import build_roadmap, to_dataframe, to_markdown
from mvc.schema import Compartment, Platform, Route, TrialScenario, Vaccine
from mvc.strategy.agent import (
    critique,
    parse_scenario_rules,
    run_agent,
    trace_json,
)
from mvc.strategy.optimal_design import compare_designs, optimal_days, profile_for
from mvc.strategy.rules import evidence_timepoints, propose
from mvc.strategy.rules import to_markdown as strategy_md
from mvc.synthetic import demo_dataset


@pytest.fixture(scope="module")
def eb():
    return load()


def scenario(**kw) -> TrialScenario:
    base = dict(
        name="test",
        vaccine=Vaccine(name="LAIV", pathogen="influenza",
                        platform=Platform.live_attenuated, route=Route.intranasal),
        n_participants=30, max_visits=6, follow_up_days=180, questions=["peak", "durability"])
    base.update(kw)
    return TrialScenario(**base)


# --- rule engine ----------------------------------------------------------- #
def test_proposal_is_internally_consistent(eb):
    p = propose(scenario(), eb)
    assert 0 in p.sampling_days
    assert len(p.sampling_days) <= p.scenario.max_visits
    assert all(d <= p.scenario.follow_up_days for d in p.sampling_days)
    assert p.endpoints and p.options


def test_proposal_builds_a_valid_trial_design(eb):
    """The pydantic validators are the real test: a design that violates them raises."""
    design = propose(scenario(), eb).to_trial_design()
    assert design.arms and design.sampling and design.endpoints


def test_mucosal_route_gets_a_mucosal_primary_endpoint(eb):
    p = propose(scenario(), eb)
    primary = [e for e in p.endpoints if e.primary]
    assert primary and primary[0].compartment is Compartment.nasal


def test_injected_route_gets_a_systemic_primary_endpoint(eb):
    im = Vaccine(name="IIV", pathogen="influenza", platform=Platform.inactivated,
                 route=Route.intramuscular)
    p = propose(scenario(vaccine=im), eb)
    primary = [e for e in p.endpoints if e.primary]
    assert primary and primary[0].compartment is Compartment.serum


def test_endpoints_are_always_backed_by_a_sampling_method(eb):
    p = propose(scenario(questions=["peak", "durability", "correlate_of_protection"]), eb)
    assert {e.method for e in p.endpoints} <= set(p.sampling_methods)


def test_correlate_question_adds_the_cellular_endpoint(eb):
    without = propose(scenario(questions=["peak"]), eb)
    with_ = propose(scenario(questions=["peak", "correlate_of_protection"]), eb)
    assert len(with_.endpoints) > len(without.endpoints)
    assert any(e.endpoint_id == "iga_asc" for e in with_.endpoints)


def test_durability_question_forces_a_late_visit(eb):
    p = propose(scenario(questions=["durability"]), eb)
    assert max(p.sampling_days) >= 90


def test_options_declare_assumption_status_honestly(eb):
    p = propose(scenario(), eb)
    for o in p.options:
        assert o.assumption == (len(o.evidence) == 0)
        if not o.assumption:
            assert all(e.quote.strip() and e.citation.strip() for e in o.evidence)


def test_every_cited_quote_exists_in_its_source(eb):
    from mvc.evidence.extract import quote_in_source

    index = {f.finding_id: s for s in eb.studies for f in s.findings}
    for o in propose(scenario(), eb).options:
        for e in o.evidence:
            assert quote_in_source(e.quote, index[e.finding_id].source_text)[0]


def test_coverage_counts_add_up(eb):
    c = propose(scenario(), eb).coverage
    assert c["evidence_backed"] + c["assumptions"] == c["options"]


def test_open_questions_are_always_raised(eb):
    assert propose(scenario(), eb).open_questions


def test_tight_visit_budget_is_respected_and_reported(eb):
    """Two visits cannot answer four questions: truncate, and say what was dropped."""
    p = propose(scenario(max_visits=2, questions=["peak", "durability"]), eb)
    assert len(p.sampling_days) <= 2
    assert any("budget" in n.lower() or "truncat" in n.lower() for n in p.design_notes)


def test_evidence_timepoints_come_from_citable_studies_only(eb):
    days = evidence_timepoints(eb)
    assert days and all(0 <= d <= 365 for d in days)


def test_strategy_markdown_marks_assumptions_and_carries_the_disclaimer(eb):
    md = strategy_md(propose(scenario(), eb))
    assert "ASSUMPTION" in md
    assert "not clinical advice" in md.lower()
    assert "For the expert" in md


# --- optimal design -------------------------------------------------------- #
@pytest.mark.parametrize("route,platform,expected", [
    (Route.intranasal, Platform.live_attenuated, "laiv_like"),
    (Route.intranasal, Platform.adenovirus_vector, "adv_in_like"),
    (Route.intramuscular, Platform.inactivated, "iiv_im_like"),
])
def test_profile_selection(route, platform, expected):
    v = Vaccine(name="v", pathogen="influenza", platform=platform, route=route)
    assert profile_for(scenario(vaccine=v)) == expected


def test_optimal_design_keeps_mandatory_days_and_respects_the_budget():
    res = optimal_days(scenario(max_visits=6), mandatory=[0, 7], n_draws=8, seed=0)
    assert {0, 7} <= set(res.days)
    assert len(res.days) == 6
    assert res.days == sorted(res.days)


def test_optimal_design_is_deterministic():
    a = optimal_days(scenario(), mandatory=[0], n_draws=8, seed=1).days
    b = optimal_days(scenario(), mandatory=[0], n_draws=8, seed=1).days
    assert a == b


def test_optimal_design_beats_a_deliberately_bad_schedule():
    """Information criterion must prefer spread-out days over clustered ones."""
    scn = scenario(max_visits=5)
    opt = optimal_days(scn, mandatory=[0], n_draws=12, seed=0)
    scores = compare_designs(scn, {"optimal": opt.days, "clustered": [0, 1, 3, 5, 7]},
                             n_draws=12, seed=0)
    assert scores["optimal"] > scores["clustered"]


def test_optimal_design_never_samples_past_follow_up():
    res = optimal_days(scenario(follow_up_days=60, max_visits=5), n_draws=8)
    assert max(res.days) <= 60


# --- scenario parsing ------------------------------------------------------ #
@pytest.mark.parametrize("text,route,platform", [
    ("an intranasal live attenuated flu vaccine", Route.intranasal, Platform.live_attenuated),
    ("injected mRNA covid vaccine", Route.intramuscular, Platform.mrna),
    ("inhaled adenovirus vectored vaccine", Route.inhaled, Platform.adenovirus_vector),
])
def test_rule_parser_reads_route_and_platform(text, route, platform):
    scn = parse_scenario_rules(text)
    assert scn.vaccine.route is route and scn.vaccine.platform is platform


def test_rule_parser_reads_numbers_and_questions():
    scn = parse_scenario_rules("nasal flu vaccine in 48 participants, 4 visits, 12 months of follow up, durability")
    assert scn.n_participants == 48 and scn.max_visits == 4 and scn.follow_up_days == 360
    assert "durability" in scn.questions


def test_rule_parser_detects_a_comparator_and_children():
    scn = parse_scenario_rules("compare a nasal vaccine versus the injected one in children")
    assert scn.comparator is not None
    assert scn.population.pediatric and scn.population.age_max <= 17


def test_rule_parser_never_invents_a_pathogen():
    assert parse_scenario_rules("some vaccine, 3 visits").vaccine.pathogen == "unspecified"


# --- agent ----------------------------------------------------------------- #
def test_agent_runs_and_reports(eb):
    st = run_agent("nasal LAIV versus injected IIV in 40 adults, 6 visits, durability", eb)
    assert st.proposal and st.critique and st.report
    assert "Self-check" in st.report and "Agent trace" in st.report
    assert st.parser in ("rules", "llm")


def test_agent_self_corrects_an_impossible_request(eb):
    """3 visits + durability is contradictory; the agent must notice and repair once.

    Pinned to the rule parser. Left free, this test passed on a machine with no
    text model and failed on one with `qwen2.5:3b` installed — not because the
    agent's logic differed, but because the model read "3 visits" as 6, so there
    was no contradiction left for the agent to notice. A test of the agent must
    not depend on which optional models the machine happens to have.
    """
    st = run_agent("intranasal adenovirus covid vaccine, 3 visits, 90 days follow up, durability",
                   eb, use_llm=False)
    assert st.parser == "rules"
    assert st.revisions == 1
    assert st.critique.passed
    assert max(st.proposal.sampling_days) >= 90


def test_agent_revision_is_bounded(eb):
    st = run_agent("x", eb, use_llm=False)
    assert st.revisions <= 1


def test_the_rule_parser_reads_an_explicit_visit_count_correctly(eb):
    """The claim the "rules vs LLM" panel rests on, pinned as a test.

    A 3B model asked for a JSON scenario returned `max_visits: 6` — the value
    from its own prompt's example — for a sentence that says "3 visits". The
    rules, which look for a digit next to the word, got it right. This is the
    honest version of "we have an LLM": on a plain, explicit number the
    keyword parser is not merely adequate, it is better, and the model's
    advantage lies elsewhere (negation, spelled-out numbers, unusual order).
    """
    from mvc.strategy.agent import parse_scenario_rules
    for n in (2, 3, 7, 11):
        s = parse_scenario_rules(f"intranasal LAIV, {n} visits, 90 days follow up")
        assert s.max_visits == n, f"'{n} visits' parsed as {s.max_visits}"


def test_critique_catches_a_tampered_quote(eb):
    p = propose(scenario(), eb)
    backed = next(o for o in p.options if o.evidence)
    backed.evidence[0].quote = "a sentence that appears in no abstract whatsoever"
    c = critique(p, eb)
    assert not c.passed and not c.checks["quotes_verified"]


def test_critique_catches_a_missing_baseline(eb):
    p = propose(scenario(), eb)
    p.sampling_days = [d for d in p.sampling_days if d != 0]
    c = critique(p, eb)
    assert not c.checks["baseline_present"]


def test_critique_catches_a_budget_violation(eb):
    p = propose(scenario(max_visits=4), eb)
    p.sampling_days = [0, 3, 7, 14, 28, 56, 180]
    assert not critique(p, eb).checks["budget_respected"]


def test_trace_json_is_serialisable(eb):
    import json

    data = json.loads(trace_json(run_agent("nasal flu vaccine, 5 visits", eb)))
    assert data["critique"] and data["scenario"] and data["log"]


# --- roadmap --------------------------------------------------------------- #
def test_roadmap_derives_tasks_from_the_run(eb):
    st = run_agent("nasal LAIV vs injected IIV in 40 adults, 7 visits, durability", eb)
    rm = build_roadmap(st, demo_dataset(n=10))
    assert len(rm.tasks) >= 10
    assert all(t.acceptance.strip() and t.owner.strip() and t.origin.strip() for t in rm.tasks)
    assert {t.month for t in rm.tasks} <= {1, 2, 3}


def test_every_unsupported_option_becomes_a_validation_task(eb):
    st = run_agent("nasal flu vaccine, 6 visits, durability", eb)
    rm = build_roadmap(st)
    assumptions = [o for o in st.proposal.options if o.assumption]
    assert len(rm.assumptions_to_test) == len(assumptions)
    for o in assumptions:
        assert any(o.option_id in t.origin for t in rm.tasks)


def test_roadmap_assigns_specialists_to_specialist_questions(eb):
    st = run_agent("nasal flu vaccine, 6 visits, durability, correlates of protection", eb)
    owners = {t.owner for t in build_roadmap(st).tasks}
    assert "biostatistician" in owners


def test_roadmap_flags_the_unverified_studies(eb):
    st = run_agent("nasal flu vaccine, 6 visits", eb)
    rm = build_roadmap(st)
    assert any("placeholder" in t.title.lower() or "verify" in t.title.lower() for t in rm.tasks)


def test_roadmap_ip_section_states_facts_and_questions_only(eb):
    st = run_agent("nasal flu vaccine, 6 visits", eb)
    rm = build_roadmap(st)
    assert rm.ip_facts and rm.ip_questions
    assert all(q.strip().endswith("?") or "(" in q for q in rm.ip_questions)
    md = to_markdown(rm)
    assert "lawyer" in md.lower()


def test_roadmap_dataframe_is_ordered_by_week(eb):
    st = run_agent("nasal flu vaccine, 6 visits", eb)
    df = to_dataframe(build_roadmap(st, demo_dataset(n=8)))
    assert df["week"].is_monotonic_increasing


# --------------------------------------------------------------------------- #
# Rules vs LLM comparison
# --------------------------------------------------------------------------- #

def test_parser_comparison_degrades_to_rules_without_a_model():
    """The comparison must never be the thing that breaks the demo.

    On a machine with no text model pulled — which is the normal case, and was
    the author's own case throughout — `compare_parsers` returns the rules
    result, says why the model did not run, and does not raise.
    """
    from mvc.strategy.agent import compare_parsers
    r = compare_parsers("intranasal LAIV vs injected IIV in 40 adults, 7 visits, durability")
    assert r["rules"]["n_participants"] == 40
    assert r["rules"]["route"] == "intranasal"
    if not r["llm_ran"]:
        assert r["error"], "the LLM did not run and no reason was given"
        assert r["llm"] is None
        assert r["differences"] == []


def test_parser_comparison_never_diffs_the_provenance_note():
    """`notes` records which parser ran, so including it would report a
    disagreement on every single sentence."""
    from mvc.strategy.agent import _COMPARED_FIELDS, _flatten, parse_scenario_rules
    s = parse_scenario_rules("intranasal LAIV in 30 adults over 90 days")
    assert "notes" not in _COMPARED_FIELDS
    assert "notes" not in _flatten(s)
    assert set(_COMPARED_FIELDS) <= set(_flatten(s)) | {"comparator_route"}


def test_participant_count_survives_adjectives_and_resists_time_units():
    """A parser that silently substitutes its default for a number the user
    typed is worse than one that fails loudly: the dashboard showed "30"
    beside a sentence saying "40 healthy adults" and nothing flagged it."""
    from mvc.strategy.agent import parse_scenario_rules as P
    cases = [
        ("40 healthy adults", 40),
        ("120 children aged 2 to 8", 120),
        ("48 healthy young volunteers", 48),
        ("25 patients", 25),
        ("40 sujets sains", 40),
        ("12 people", 12),
        # widening the pattern must not start eating follow-up durations
        ("follow-up over 180 days in adults", 30),
        ("seen at 7 visits by trained adults", 30),
        ("a nasal vaccine with no number at all", 30),
    ]
    for txt, want in cases:
        got = P("intranasal vaccine, " + txt).n_participants
        assert got == want, f"{txt!r} parsed as {got}, expected {want}"
