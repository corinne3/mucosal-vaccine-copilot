# Architecture

This is the document to read before an interview about the project. It states what the
layers are, why each boundary is where it is, and which trade-offs were taken knowingly.

---

## 1. The constraint that shaped everything

The hard problem in this domain is not fitting a curve. It is that **a number without
its measurement context is meaningless, and silently combining such numbers produces
a result that looks right and is wrong.**

Three facts drive the design:

1. **Compartments are separate.** Mucosal and blood antibody responses are induced
   separately and correlate weakly (Thwaites 2023; Bean 2024). A serum value cannot
   stand in for a nasal one.
2. **Mucosal sampling is not standardised.** A lavage dilutes the sample by an unknown
   factor; an absorptive strip does not. Raw values from the two devices are not on one
   scale.
3. **Assay units are often lab-specific.** "AU/mL" means whatever that laboratory's
   standard curve means.

A conventional pipeline (load → clean → average → plot) destroys exactly this
information, in the step called "cleaning". So the architecture inverts the usual
priority: **context is a first-class citizen and travels with every value**, and the
comparison rules are an explicit, inspectable artefact rather than an implicit
consequence of a `groupby`.

---

## 2. Layers

```
                 ┌──────────────────────────────────────────────┐
  adapters       │  CLI      Streamlit      MCP server          │
                 └──────────────────────────────────────────────┘
                                    │  (no business logic here)
                 ┌──────────────────────────────────────────────┐
  orchestration  │  agent: parse → propose → retrieve →         │
                 │         critique → (revise ×1) → report      │
                 └──────────────────────────────────────────────┘
                                    │
                 ┌──────────────────────────────────────────────┐
  engines        │  rules │ optimal_design │ comparability │    │
                 │  kinetics │ roadmap │ search │ graph         │
                 └──────────────────────────────────────────────┘
                                    │
                 ┌──────────────────────────────────────────────┐
  domain model   │  schema.py — pydantic, validators that       │
                 │  refuse incoherent designs                   │
                 └──────────────────────────────────────────────┘
                                    │
                 ┌──────────────────────────────────────────────┐
  data           │  evidence base (verified) │ raw corpus │     │
                 │  synthetic generator                         │
                 └──────────────────────────────────────────────┘
```

**Rule:** dependencies point downward only. The engines never import an adapter; the
domain model imports nothing from the project. This is why the same logic serves a web
UI, a terminal and an MCP client with no duplication — and why the test suite can
exercise the engines without spinning up anything.

---

## 3. Key decisions and their trade-offs

### 3.1 Rules, not a model, for comparability

**Decision.** Comparability is a list of ~10 small pure functions, each returning at
most one flag with a code, a message and a remedy. Severity is the maximum over flags.

**Why.** The brief asks for *transparent* flagging. A reviewer must be able to read why
two curves were separated, and a domain expert must be able to disagree with a specific
rule rather than with "the model". Rules are also trivially testable: 13 labelled pairs
pin the whole engine (`eval/run.py::COMPARABILITY_CASES`).

**Trade-off.** Rules do not generalise to cases nobody anticipated. Accepted: in a
regulated domain, a wrong-but-explainable verdict is recoverable, a wrong-but-opaque one
is not.

**Alternative rejected.** Learning comparability from data. There is no labelled corpus,
and the output would be unauditable.

### 3.2 Three-level verdict, not a boolean

`comparable` / `conditional` / `not_comparable`. The middle level is what makes the tool
usable: "different labs" is a real caveat but not a reason to hide the data. A boolean
would force every caveat into either silence or refusal.

### 3.3 Fold-rise as the only cross-compartment scale

When compartments differ, the engine's remedy is always the same: compare *shape*
(fold-rise over the subject's own baseline, time to peak, half-life), never absolute
level. This is why a day-0 sample is non-negotiable, and why the dashboard has a
dedicated fold-rise view with its own axis.

### 3.4 Bateman function for kinetics

**Decision.** `y(t) = b + A·(e^{-ke·τ} − e^{-ka·τ})`, fitted on log10 residuals,
uncertainty by **subject-level** bootstrap.

**Why.** Four interpretable parameters, each mapping onto a question the brief asks
(baseline, amplitude, time to peak, durability). Log residuals because antibody noise is
multiplicative. Subject-level resampling because repeated measures on one participant are
correlated — resampling rows would understate uncertainty, which is the one error this
project must not make.

**The important behaviour:** with fewer than 4 distinct timepoints the fit **declares
itself unidentifiable** and returns medians with a note, instead of a confident curve.
A tool that reports a half-life from three points is worse than no tool.

**Trade-off.** A two-compartment or mechanistic immunological model would be richer.
Rejected for a 48-hour build: more parameters, less identifiable, harder to explain.

### 3.5 Bayesian D-optimal design for sampling days

**Decision.** Greedy maximisation of `E_θ[log det FIM]` over candidate days, with θ drawn
from a prior, information summed over the mucosal and systemic responses (paired visits).

**Why.** The real constraint is the visit budget, and "which days" is exactly a design-of-
experiments question. D-optimality shrinks the joint confidence ellipsoid of the kinetic
parameters, so the chosen days are the ones that most reduce uncertainty about peak and
half-life.

**Trade-off and honesty.** The result is only as good as the prior, and the prior is an
illustrative assumption. The tool therefore prints that sentence next to the schedule,
and anchor visits (baseline, post-dose windows, a late visit) come from the *reported*
timepoints of the evidence base rather than from the prior. Greedy, not exhaustive:
near-optimal, and it runs in a second on a CPU.

### 3.6 Hybrid retrieval with RRF, and why abstracts are down-weighted

BM25 is hand-written (30 lines) so it can be explained; dense retrieval uses local
embeddings. Fusion is Reciprocal Rank Fusion — `Σ 1/(k + rank)` — which needs no score
calibration between retrievers.

One tuned parameter deserves explanation, because the eval suite forced it: **abstract
chunks are weighted 0.45, finding chunks 1.0.** An abstract contains every claim of the
paper at once, so it dominates lexical overlap and masks the precise finding a
recommendation must cite. Down-weighting restores the intended ranking. Recall@3 went
0.67 → 0.79 on the gold set, with the gold set untouched.

### 3.7 Quote verification is the real anti-hallucination mechanism

**Decision.** Every finding must carry a verbatim quote. Verification requires *both*
high character similarity on the best-matching window *and* an identical multiset of
content words.

**Why the second condition.** This was a bug the eval suite caught. With character
similarity alone at 0.92, these all passed as "found in source":

- `did not induce` → `did induce`
- `lower levels` → `higher levels`
- `mucosal IL-33` → `systemic IL-33`

A single-word flip barely moves the character ratio and inverts the meaning. A
verification step that lets those through is worse than none: it stamps a fabrication as
sourced. Detection went 94% → 100% on 86 corrupted quotes, with real quotes still
accepted at 100%.

**Consequence in the architecture.** `EvidenceLevel` is a lattice, and only
`verified_abstract`, `verified_fulltext`, `llm_extracted` and `extractive_auto` are
citable. `to_verify` placeholders exist in the base so the gaps are visible, and the
graph refuses to return them for citable lookups.

### 3.8 The LLM is optional, everywhere

Every AI-assisted step has a deterministic twin, chosen at runtime by probing Ollama.
On a CPU laptop with no credits and intermittent wifi, this is not defensive
programming, it is the difference between a demo and a story about a demo. It also makes
CI possible: no test needs a model.

### 3.9 Self-critique with a bounded revision loop

The agent grades its own output on objective criteria (unsupported-option share,
quote verifiability, budget respected, baseline present, late visit when durability is
asked, open questions non-empty) and revises **at most once**, then reports regardless
with the critique attached.

**Why bounded.** An unbounded "improve until satisfied" loop burns tokens and, worse,
drifts: a model asked to fix its own output tends to make it longer and more confident,
not more correct. One mechanical repair pass, then transparency.

What a revision may change is deliberately narrow: raise the visit budget, extend
follow-up. It may **not** weaken a check or drop a constraint.

### 3.10 Synthetic data that fights back

The generator does not produce clean data. It injects, on purpose: lavage dilution,
arbitrary units, a second lab with a bias, LLOQ censoring, missing visits, a sparse
series, titres snapped to two-fold dilutions, and a responder fraction below 1.

**Why.** A demo on clean data proves nothing about a tool whose value is catching
dirt. Here the dirt is the test fixture: 14 non-comparable pairs on the demo dataset,
flagged with reasons. And because truth is known, the kinetic fit can be *graded*
(`kinetics_peak_rel_error` 0.12, bootstrap CI coverage 8/8) rather than eyeballed.

### 3.11 A roadmap derived, not written

`build_roadmap` reads the run's own results: each unsupported option becomes a validation
task, each open question gets an owner matched by keyword, each failed self-check becomes
a fix, each thin series becomes "add timepoints", each non-comparable pair becomes
"harmonise". Hand-written roadmaps are wish lists; this one cannot claim a gap does not
exist, because the gap generated the task.

The IP section states **facts and open questions only**. IP strategy is a lawyer's call,
and the HackLab has a patent attorney on the mentor list.

---

## 4. Data flow, one pass

```
free text
   │  parse_scenario (LLM w/ JSON schema │ keyword rules)
   ▼
TrialScenario ──────────────────────────────────┐
   │  11 rules, each citing finding ids          │
   ▼                                             │
Plan ── EvidenceResolver ── evidence base (verified quotes only)
   │                                             │
   │  anchor days (from reported timepoints)     │
   ▼                                             │
optimal_days  ── Bayesian D-optimal ─────────────┘
   ▼
StrategyProposal ── to_trial_design() ── pydantic validators (refuse incoherence)
   │
   ├── critique ── quote re-verification, budget, baseline, durability
   │      └── revise ×1 ──> re-propose
   ▼
report (markdown)  +  roadmap  +  dashboard figures
```

The measurement side is independent and joins at the dashboard:

```
CSV / synthetic ──> harmonize_units ──> comparability_matrix ──> split_comparable_groups
                                    └──> audit_table (uncertainty)
                                    └──> fit_kinetics (+ bootstrap) ──> figures
```

---

## 5. Performance

Measured on CPU only (no GPU anywhere in this project):

| Operation | Cost |
|---|---|
| Synthetic dataset (60 subjects, 6 series, 2220 rows) | ~0.3 s |
| One kinetic fit, 150 bootstrap resamples | ~0.5–1.0 s |
| Comparability matrix, 6 series (15 pairs) | < 10 ms |
| D-optimal selection, 17 candidates, 80 Jacobians | ~1 s |
| Full agent run (rule parser, no LLM) | ~2 s |
| Whole demo, objectives 1–6 | ~8 s |
| 144 tests | ~40 s |

Bootstrap count is the only real knob; it is exposed in the dashboard sidebar.

---

## 6. What I would do next

1. Replace the seed base with a systematic search, keeping the verification gate.
2. Censored-data likelihood for LLOQ instead of LLOQ/2 imputation.
3. Hierarchical (mixed-effects) kinetics: partial pooling across subjects would make
   sparse series usable instead of merely flagged.
4. Expand the retrieval gold set and add an extraction gold set with human labels.
5. Persist the evidence base in a real store (SQLite + FTS5) once it outgrows JSON.

---

## 7. Known weaknesses

- Greedy D-optimality can be beaten by exhaustive search on small budgets.
- RRF constant `k=60` is a convention, not tuned.
- The knowledge graph is in-memory; `coverage_gaps` is O(platforms × methods).
- `parse_timeframe` approximates a month as 30 days.
- The keyword scenario parser handles English and some French, and will mis-parse unusual
  phrasings — which is why the agent prints what it parsed before acting on it.
