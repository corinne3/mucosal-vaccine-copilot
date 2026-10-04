# The extras — techniques beyond the six objectives

The brief asks for six things. This document covers what was added on top, and more
importantly **why each one earns its place** rather than being technique for its own sake.
The test for every item below: does it make the output more trustworthy, or is it
decoration?

---

## 1. Knowledge graph (`evidence/graph.py`)

**What.** 88 nodes, 155 edges on the seed base: studies linked to platforms, routes,
sampling devices, compartments, assays, findings and tags.

**Why it earns its place.** Not because graphs are fashionable, but because of one query:
`coverage_gaps()`. It returns the platform × device combinations that **no** study in the
base covers. Knowing where the evidence is *absent* is as useful as knowing where it is
present, and it is the kind of question a flat JSON file cannot answer without a join you
would have to write anyway.

Also: `studies_for_tag(tag, citable_only=True)` is how a rule in objective 3 finds support,
and it enforces the citability rule structurally — `to_verify` placeholders cannot leak
into a citation (`test_graph_excludes_unverified_studies_from_citable_lookups`).

**Cost.** In-memory, rebuilt on load. `coverage_gaps` is O(platforms × methods), fine at
this size, would need indexing at 1000 studies.

---

## 2. Hybrid retrieval with RRF (`evidence/search.py`)

**What.** BM25 written by hand in ~30 lines, plus dense retrieval over local embeddings,
fused with Reciprocal Rank Fusion: `score(d) = Σ_r w · 1/(k + rank_r(d))`.

**Why hand-written BM25.** Because I wanted to be able to explain term frequency saturation
(`k1`) and length normalisation (`b`) rather than cite a library. In an interview, "we used
a retriever" and "here is the ranking function and here is why abstracts dominate it" are
very different answers.

**Why RRF rather than score blending.** It needs no calibration between retrievers. BM25
scores and cosine similarities live on incomparable scales; ranks do not. One fewer
parameter to tune and one fewer thing to get silently wrong.

**The one tuned parameter, and the honest story.** Abstract chunks weigh 0.45 against
findings at 1.0. An abstract contains every claim of the paper at once, so it dominates
lexical overlap and masks the precise finding a recommendation must cite. The eval suite
is what exposed this: recall@3 was 0.67 with two queries returning no relevant finding at
all. Down-weighting abstracts took it to **0.79** without touching the gold set.

**Graceful degradation.** No embedding model → BM25 only, and `searcher.mode` says so in
the dashboard sidebar. Capability is disclosed, never silently reduced.

---

## 3. Structured extraction with constrained decoding (`evidence/extract.py`)

**What.** A local LLM extracts `Study` records, with Ollama's `format` parameter
constraining decoding to the JSON Schema. Plus a deterministic regex extractor that selects
verbatim sentences.

**Why constrained decoding.** It removes an entire failure class — malformed JSON, missing
fields, invented enum values — at the decoder rather than in a retry loop. A 3B model on a
CPU gets one chance; schema constraints make that chance count.

**Why keep the rule-based extractor.** It is *extractive*: findings are verbatim sentences,
so it physically cannot fabricate. The worst case is an irrelevant sentence. On a train
with no model loaded, it is the difference between a working pipeline and a stalled one.

---

## 4. Quote verification (`evidence/extract.py::quote_in_source`)

**This is the most important extra in the project, and the best story in it.**

**What.** Every finding must carry a verbatim quote, checked against its source. Findings
whose quote cannot be found are **dropped**.

**The bug the eval suite caught.** The first version used character similarity at a 0.92
threshold. These all passed as "found in source":

| Source | Fake | Similarity |
|---|---|---|
| `did not induce IgA production` | `did induce IgA production` | 0.95 |
| `had lower levels of IgA` | `had higher levels of IgA` | 0.92 |
| `mucosal IL-33 release` | `systemic IL-33 release` | 0.92 |

A one-word flip barely moves the character ratio and inverts the meaning. **A verification
step that accepts those is worse than having none**: it stamps a fabrication as sourced,
which is the exact failure the whole architecture exists to prevent.

**The fix.** Two conditions, together: character similarity ≥ 0.97 on the best window
**and** an identical multiset of content words in that window. Condition 2 is the real
check; condition 1 only absorbs typographic noise from PDF extraction.

**Result.** Fake detection 94% → **100%** on 86 corrupted quotes; real quotes still
accepted at 100%. Both thresholded in CI, so the regression cannot come back.

**Why this matters beyond this project.** It is a reusable pattern for any
retrieval-augmented system that claims to cite: *character similarity is not semantic
equivalence, and negation is where the difference hides.*

---

## 5. Bayesian D-optimal design (`strategy/optimal_design.py`)

**What.** Pick sampling days by maximising `E_θ[log det FIM]`, where the Fisher information
matrix comes from the Jacobian of the kinetic model with respect to its parameters, and θ
is drawn from a prior.

**Why.** "Which days should we sample?" is a design-of-experiments question, and
D-optimality answers exactly it: shrink the joint confidence ellipsoid of the parameters
you care about. The alternative — a schedule picked by convention — leaves information on
the table within the same visit budget.

**Why Bayesian (prior averaging).** You do not know the kinetics before you measure them.
Optimising for a single point estimate would over-fit the schedule to a guess.

**Verified, not asserted.** `test_optimal_design_beats_a_deliberately_bad_schedule`
requires a spread design to outscore a clustered one. Without that test the whole module
would be unsubstantiated maths.

**The honest caveat, printed next to every output.** The prior is an illustrative
assumption, so the chosen days are only as good as it — which is why the evidence-backed
anchors are never overridden by the optimiser.

---

## 6. Agent with bounded self-critique (`strategy/agent.py`)

**What.** `parse → propose → retrieve → critique → (revise ×1) → report`, on a
hand-rolled executor with zero dependencies, plus an equivalent LangGraph build if the
package is installed.

**Why an agent at all.** Only for the messy edges: free text in, tool choice, and
self-checking. The business logic stays in the deterministic engines, which is why 40 tests
can exercise objective 3 without any model.

**Why the critique is the interesting part.** It grades on *objective* criteria — quote
verifiability, visit budget, baseline present, late visit when durability is asked, open
questions non-empty — not on an LLM's opinion of its own work. A self-critique that asks a
model "is this good?" measures nothing.

**Why bounded to one revision.** An unbounded improve-until-satisfied loop drifts: a model
fixing its own output tends to make it longer and more confident rather than more correct.
One mechanical repair pass, then report regardless with the critique attached, failures
included.

**Why a hand-rolled executor by default.** Six nodes and a conditional edge do not need a
framework, and a dependency on the critical path of a train demo is a liability. LangGraph
is offered so the same graph can be shown in either idiom.

---

## 7. Bootstrap uncertainty (`kinetics.py`)

**What.** Subject-level bootstrap: resample participants, refit, take percentiles for the
peak day, the half-life and the whole curve band.

**Why subject-level and not row-level.** Repeated measures on one participant are
correlated. Resampling rows would treat them as independent and **understate** uncertainty
— the one error a tool whose purpose is honest uncertainty must not make.

**Why bootstrap and not asymptotic standard errors.** The model is non-linear and the
sample is small; asymptotic intervals would be optimistic in exactly the regime this tool
operates in.

**The behaviour that matters most.** Fewer than four distinct timepoints for a
four-parameter model → `identifiable=False`, medians returned with a note, **no curve
drawn**. A tool reporting a half-life from three points is worse than no tool.

**Calibration is measured.** Because the synthetic generator knows the truth: CI coverage
8/8, relative error on peak day 0.12. Both thresholded in CI.

---

## 8. Figure digitisation with a vision model (`figure_digitizer.py`)

**What.** A vision-language model reads (day, value) pairs off a published kinetics plot.
Optionally preceded by `extract_figures_from_pdf` to pull the images out.

**Why it is on-topic rather than a bolt-on.** This was the "add some computer vision"
temptation, and it only survived because it solves a real problem in *this* track: papers
often report kinetics **only as a figure**, so the evidence base cannot hold the numbers.
That is a genuine gap, not an excuse to use a camera model.

**Why the validation layer is bigger than the extraction.** The model must also return the
axis ranges it believes it read, and the result is **rejected** when the axes are
implausible, the x-unit is unknown, a series has fewer than three points, or any point
falls outside the stated axis range. Rows that survive are tagged
`source="digitized_from_figure"`, which the comparability engine automatically flags as
`conditional`, and they are written to a **separate file** — never into the verified
evidence base.

**A rejection is a good demo.** It shows the validation working, which is more convincing
than a plausible-looking table nobody can check.

---

## 9. MCP server (`mcp_server.py`)

**What.** Ten tools over the same engines: `search_evidence`, `list_studies`,
`studies_by_tag`, `evidence_gaps`, `check_comparability`, `propose_strategy`,
`generate_roadmap`, `fit_kinetic_curve`, `comparability_report`, `synthetic_demo`, plus an
`evidence://studies` resource.

**Why it earns its place architecturally.** It is the third adapter over one core — CLI,
Streamlit, MCP — and it proves the layering claim rather than asserting it. Adding it
required no change to any engine. That is the whole point of the dependency rule in
`docs/ARCHITECTURE.md`.

**Why it is a good live demo.** Querying the evidence base conversationally in Claude
Desktop, with every answer carrying its verbatim quote, lands better than a slide about
provenance.

Compatible with MCP SDK v2 (`MCPServer`) and v1 (`FastMCP`) via an import fallback.

---

## 10. Eval harness (`eval/run.py`)

**What.** Seven metrics with thresholds that **fail CI**:

| Metric | Value | Threshold |
|---|---|---|
| `retrieval_recall@3` | 0.79 | ≥ 0.70 |
| `retrieval_mrr` | 0.78 | ≥ 0.60 |
| `extraction_true_acceptance` | 1.00 | ≥ 0.95 |
| `extraction_fake_detection` | 1.00 | = 1.00 |
| `comparability_accuracy` | 1.00 | = 1.00 |
| `kinetics_peak_rel_error` | 0.12 | ≤ 0.35 |
| `kinetics_ci_coverage` | 1.00 | ≥ 0.70 |

**Why this is the extra I would keep if I could keep only one.** It found two real bugs
during the build — the quote-verification leak and the abstract-dominance problem in
retrieval — neither of which would have been visible by reading the code or eyeballing
outputs. "It seems to work" is not a claim; a thresholded metric is.

**Why it needs no LLM and no network.** So it runs in the train and in CI. A quality gate
you cannot run is not a gate.

**Honest limitation.** The retrieval gold set has 12 hand-judged queries — real, but a wide
confidence interval. Expanding it is a generated roadmap task.

---

## 11. CI (`.github/workflows/ci.yml`)

Python 3.10 and 3.12: ruff, 144 tests, the eval suite, the full demo, and an
**evidence-integrity gate** that re-verifies every quote against its source and refuses any
citable study without a DOI or PMID. Artefacts uploaded on every run.

**Why the integrity gate is separate from the tests.** It guards the *data*, not the code.
Someone — including future me — editing `seed_evidence.json` by hand and mistyping a quote
would otherwise ship an unverifiable citation. The build fails instead.

---

## What was deliberately left out

Saying no is part of the design, and these were all tempting:

- **A fine-tuned domain model.** No labelled corpus, no GPU, and it would make the system
  less explainable in exchange for marginal accuracy.
- **A vector database.** 30 chunks. NumPy is the right answer; Qdrant would be résumé-driven
  development.
- **A multi-agent crew** (immunologist agent, statistician agent, writer agent). More moving
  parts, more drift, harder to test, and it would obscure the fact that the real expertise
  must come from the humans in the room.
- **A mechanistic immunological model** (germinal centres, plasma cell compartments).
  Scientifically richer, far less identifiable from the available data, and unexplainable in
  a 48-hour review.
- **Computer vision on raw microscopy or assay plates.** The genuinely off-topic version of
  the vision idea. Dropped.
- **A full ETL framework.** Six objectives, one dataset shape. Pandas and explicit functions
  beat an orchestrator here.
