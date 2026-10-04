# Objective 3 — Scenario in, transparent strategy out

> *"a prototype that accepts a trial scenario and proposes a transparent sampling and endpoint strategy"*

**Modules:** `src/mvc/strategy/` (`rules`, `optimal_design`, `agent`) ·
**Tests:** `tests/test_strategy_and_roadmap.py` (40) ·
**Run:** `python -m mvc.cli propose "..." --print`

---

## The reading of "transparent" this project takes

Transparent does not mean "the output is readable". It means **a reviewer can trace every
choice to its reason, and can see which choices have no reason behind them.**

So the output is not a plan. It is a list of `Option` objects:

```python
class Option(BaseModel):
    option_id: str
    category: str              # endpoint | sampling_method | timepoints | analysis | open_question
    choice: str                # what is proposed
    rationale: str             # why, in engineering terms
    evidence: list[EvidenceRef]  # citation + VERBATIM quote, resolved from the base
    assumption: bool           # True when evidence is empty — printed in red
    expert_review: str         # what the domain expert must confirm or reject
```

`assumption` is computed, never asserted: `assumption = (len(evidence) == 0)`. A rule
cannot claim support it does not have, because the resolver refuses non-citable sources and
the field follows mechanically. A test pins it
(`test_options_declare_assumption_status_honestly`).

On the demo scenario: **10 options, 8 evidence-backed, 2 assumptions.** The 2 are printed
as `ASSUMPTION — no supporting evidence` and each becomes a validation task in the roadmap.

## Why options and not recommendations

The author is not an immunologist. A tool that emitted "use nasosorption at days 0, 7, 28"
would be making clinical claims it cannot support, and would invite a team to skip the one
conversation that matters. So every option carries an `expert_review` question, and the
proposal ends with `open_questions` — decisions the tool explicitly refuses:

- endpoint ranking (primary vs secondary) — clinical and regulatory
- sample size and power — biostatistician
- device acceptability and assay validation — lab lead
- correlates of protection — nobody has one for mucosal flu vaccines **[evidence]**

`test_open_questions_are_always_raised` makes an empty list a test failure. A tool with no
open questions on this subject is lying.

## The rule engine

11 rules, each a small pure function appending to a mutable `Plan`:

| Rule | Proposes | Evidence |
|---|---|---|
| `r_sampling_devices` | one nasal device for the whole trial | — (assumption, engineering constraint) |
| `r_paired_compartments` | nasal and serum at the same visits | ✓ |
| `r_endpoint_candidates` | mucosal endpoint carried alongside systemic | ✓ |
| `r_normalisation` | report raw **and** normalised to total IgA | — (assumption) |
| `r_baseline_and_prior_immunity` | day-0 in every compartment | ✓ |
| `r_post_dose_windows` | anchors at dose+7, dose+28 | ✓ |
| `r_durability_visit` | a late visit when durability is asked | ✓ |
| `r_responder_rate_and_size` | pre-specify responder definition, report the fraction | ✓ |
| `r_assay_standardisation` | one standard, one lab, or bridging samples | ✓ |
| `r_cellular_optional` | blood IgA-secreting plasmablasts (exploratory) | ✓ |
| `r_uncertainty_disclosure` | ship CIs, censoring and comparability flags | ✓ |

Rules register themselves with a decorator, so adding one is a function plus a test. Each
rationale is stated in **engineering** terms wherever possible — "the comparability engine
flags this", "fold-rise is impossible without day 0" — rather than borrowed clinical
authority.

The anchor windows come from `evidence_timepoints(eb)`: the timepoints **actually
reported** by the citable studies, parsed out of their abstracts and registry entries. The
schedule is grounded in what trials did, not in an invented biology.

## Bayesian D-optimal design for the remaining visits

Anchors fill some of the visit budget. The rest is a design-of-experiments problem: *which
days most reduce uncertainty about the kinetic parameters?*

- Model: the Bateman curve of objective 4, with four log-parameters θ
- Sensitivity: `J = ∂ log10 y / ∂θ` at each candidate day (central differences)
- Information: `FIM = JᵀJ / σ²`
- Criterion: **maximise `E_θ[log det FIM]`**, θ drawn from a prior — D-optimality shrinks
  the joint confidence ellipsoid of the parameters
- Summed over the mucosal **and** systemic responses, because visits are paired
- Greedy: add the day with the largest gain until the budget is spent

Verified empirically rather than asserted: `test_optimal_design_beats_a_deliberately_bad_schedule`
requires a spread design to score above a clustered one.

**The honest part.** The prior is one of the project's illustrative assumptions, so the
chosen days are only as good as it. `design_notes` prints exactly that sentence next to
every schedule, and the anchors — which carry the evidence — are never overridden by the
optimiser.

## The agent

```
parse ──> propose ──> retrieve ──> critique ──┬──> report
             ▲                                │
             └────────── revise (×1) ─────────┘
```

**`parse`** — free text to `TrialScenario`. LLM with JSON-schema-constrained decoding when
available; otherwise a keyword parser that handles route, platform, pathogen, participant
count, visit count, follow-up, comparator, paediatric and the question set. The fallback
**never invents a pathogen** (`test_rule_parser_never_invents_a_pathogen`) — unknown stays
`unspecified`.

**`retrieve`** — for each open question, pull supporting chunks from the evidence base, so
the expert reading the briefing has the literature next to the question.

**`critique`** — the interesting node. The agent grades its own output on objective
criteria:

| Check | Fails when |
|---|---|
| `assumption_share_ok` | more than 40% of options are unsupported |
| `quotes_verified` | a cited quote is not in its source (re-verified here) |
| `budget_respected` | more visits proposed than the budget |
| `baseline_present` | no day 0 |
| `within_followup` | a visit after follow-up ends |
| `late_visit_for_durability` | durability asked, no late visit |
| `experts_flagged` | no open question raised |

**`revise`** — bounded to **one** pass, and allowed to change only two things: raise the
visit budget, extend follow-up. It may not weaken a check or drop a constraint.

Worked example — a contradictory request, *"intranasal adenovirus COVID vaccine in
children, 3 visits, 90 days follow up"* with durability implied:

```
parse: rules -> intranasal adenovirus_vector, 3 visits, questions=['peak', 'durability']
propose: 10 options, visits [0, 7, 28]
critique: fail (1) — Durability asked but no late visit: half-life will not be identifiable
revise: extended follow-up and freed one visit slot for a late sample
propose: 10 options, visits [0, 7, 28, 180]
critique: pass
```

It noticed that 3 visits cannot answer a durability question, repaired it once, and said so
in the trace. `test_agent_self_corrects_an_impossible_request` pins this exact behaviour.

**Why bounded.** An unbounded "improve until satisfied" loop drifts: a model asked to fix
its own output tends to make it longer and more confident, not more correct. One mechanical
repair, then transparency — the critique is printed in the report either way, failures
included.

## When the budget simply cannot stretch

With `max_visits=2` and four questions, there is no clever answer. The engine truncates to
the budget, records *what it dropped* in `design_notes`, and adds an open question asking
which question the team is willing to give up. It does not quietly exceed the budget, and
it does not pretend the schedule answers everything
(`test_tight_visit_budget_is_respected_and_reported`).

## Output

`outputs/strategy.md` — the expert-facing briefing: proposed visits, every option with its
support and its question, the visit-selection notes, the out-of-scope list, the endpoint
table, the self-check results, the retrieved evidence, and the full agent trace.
`outputs/strategy_trace.json` — the machine-readable version.

`to_trial_design()` materialises the options as a validated `TrialDesign`, which means the
objective-1 validators get a second say: an incoherent proposal cannot even be
constructed (`test_proposal_builds_a_valid_trial_design`).

## Checks

```bash
python -m mvc.cli propose "intranasal LAIV vs injected IIV in 40 adults, 7 visits, durability" --print
python -m mvc.cli propose "nasal flu vaccine, 2 visits, durability and correlates"   # watch it refuse to over-promise
pytest tests/test_strategy_and_roadmap.py -q
```
