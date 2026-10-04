# Technical documentation — stack, architecture, decisions

Mucosal Vaccine Copilot, v0.1.0. Every figure in this document was produced by
running the code, not recalled.

| | |
|---|---|
| Python | 3.10+ (CI: 3.10 and 3.12) |
| Source | 5 584 lines across 26 modules |
| Tests | 1 294 lines, **199 tests** |
| Evaluation | 8 gating metrics + 2 informational |
| Evidence base | 11 studies (7 citable), 40 verified findings, 47 retrievable chunks |
| Real-world case | 6 consortia → 38 measurement contexts → 561 pairs |

---

## 1. The one idea, stated as an engineering constraint

Two antibody numbers are comparable only if they were produced the same way.

This is not a disclaimer at the bottom of a chart — it is a **type constraint**.
Every measurement carries a `MeasurementContext` of ten fields, a rule engine
decides what may be compared with what, and the plotting layer is *forbidden*
from drawing non-comparable series on a shared absolute axis. Putting a nasal
lavage IgA next to a serum IgG on one axis is not a questionable chart; in this
codebase it is unrepresentable.

The text side obeys the same rule: every recommendation must point at a
**verbatim quote** from a real paper, and a quote that cannot be found in its
source is dropped automatically. What remains unsupported is labelled
`ASSUMPTION`, in red, rather than quietly phrased as fact.

---

## 2. Stack

### 2.1 Runtime dependencies, and why each one is there

| Package | Role | Why not something else |
|---|---|---|
| `pydantic>=2.6` | the domain model, with validators | `extra="forbid"` turns a typo in a column name into an error instead of a silently ignored field |
| `pandas>=2.1` | measurement tables | the data is tabular and small; a dataframe is the honest shape |
| `numpy>=1.26` | numerics, bootstrap resampling | |
| `scipy>=1.11` | `curve_fit` for the Bateman model, `linalg` for the Fisher information matrix | |
| `networkx>=3.2` | knowledge graph (studies ↔ methods ↔ compartments ↔ tags) | the graph has ~100 nodes; a graph database would be theatre |
| `plotly>=5.20` | figures, in the dashboard and as standalone HTML | interactive hover matters when a point may be a censored value |
| `streamlit>=1.33` | the dashboard (extra `[app]`) | |

### 2.2 What is deliberately **absent**

**No `torch`, no `transformers`, no `langchain`, no `langgraph` on the execution
path, no vector database, no API key, no cloud call.**

This is a decision, not a limitation:

- the laptop this was built for is **CPU-only, with no GPU and no paid credits**;
- a hackathon demo that needs the wifi is a demo that fails;
- BM25 in 30 readable lines is auditable in a way that an opaque embedding
  index is not — and on this corpus it reaches recall@5 0.86 on its own;
- an agent written as an explicit state machine (`NODES` dict, 7 objective
  self-checks) can be traced line by line in an interview. A framework graph
  cannot.

`langgraph` and `mcp` are declared as *optional* extras for interoperability.
Neither is imported on any path the demo uses.

### 2.3 The optional local LLM

Models run through [Ollama](https://ollama.com), locally, with **a
deterministic fallback at every single call site**:

| Step | With a local model | Without |
|---|---|---|
| Scenario parsing | JSON-schema-constrained decoding | keyword parser (`parse_scenario_rules`) |
| Paper extraction | structured, quote-verified | verbatim-sentence extraction by regex |
| Retrieval | BM25 + embeddings, RRF-fused | BM25 only (recall@3 0.77) |
| Figure digitisation | vision model | unavailable — and it says so |

Defaults: `qwen2.5:3b`, `nomic-embed-text`, `qwen2.5vl:3b`. Override with
`MVC_LLM_MODEL`, `MVC_EMBED_MODEL`, `MVC_VLM_MODEL`, `OLLAMA_HOST`.

`src/mvc/llm.py` is **102 lines of stdlib `urllib`** — no `openai`, no
`ollama-python`. One less dependency, and the whole client fits on two screens.

---

## 3. Module map

```
src/mvc/
  schema.py            373  domain model; validators make incoherent designs unrepresentable
  comparability.py     329  the rule engine — 10 pure rules, 3 verdict levels
  kinetics.py          209  Bateman fitting + subject-level bootstrap
  synthetic.py         210  generator that INJECTS the heterogeneity to be caught
  consortia.py         288  Table 1 of the workshop report → the engine
  figures.py           269  plotly figures that obey the comparability verdicts
  roadmap.py           206  roadmap derived from the run's own gaps
  figure_digitizer.py  166  option — vision model reads a published figure
  mcp_server.py        150  option — MCP adapter
  llm.py               102  minimal Ollama client, stdlib only
  cli.py               357  one command per objective
  evidence/
    fetch.py           134  retrieve papers and trial registrations
    ingest.py          150  PDF/XML → text
    extract.py         333  structured extraction + QUOTE VERIFICATION
    search.py          242  BM25 + embeddings + Reciprocal Rank Fusion
    graph.py           108  knowledge graph, coverage gaps
    store.py            79  load / merge / chunk
  strategy/
    rules.py           518  11 rules → candidate options, each evidence-backed or flagged
    optimal_design.py  122  Bayesian D-optimal sampling days
    agent.py           476  bounded state machine + self-critique
  eval/run.py          282  8 gating metrics + 2 informational
app/dashboard.py       472  8 tabs
```

---

## 4. The seven pieces worth explaining

### 4.1 The comparability engine — `comparability.py`

Ten pure functions, each taking two `MeasurementContext` objects and returning
either `None` or a `Flag` carrying a code, a human message and a **remedy**:

`different_compartment` · `mucosal_sampling_method` · `different_assay` ·
`different_isotype` · `different_normalization` · `different_unit` ·
`different_antigen` · `different_lab` · `digitized_source` · `mixed_synthetic`

Three verdict levels: `comparable` / `conditional` / `not_comparable`.

**The engine never sees a measured value.** It takes metadata only. That is what
makes it testable against a ground truth, and what lets it run on published
methods tables where no values exist at all (§4.7).

The subtle rule is `mucosal_sampling_method`: two mucosal samples taken with
different devices are **not comparable** — a lavage dilutes by a large and
variable factor, an absorptive strip does not — **unless both are normalised to
total IgA**, in which case the dilution largely cancels and the verdict softens
to `conditional`. That one conditional is the entire reason normalisation is a
first-class field of the model.

### 4.2 Kinetics — `kinetics.py`

Bateman function, `y(t) = b + A·(e^{−ke·t} − e^{−ka·t})`, fitted on **log10
residuals** because antibody concentrations are log-normal and a least-squares
fit on raw values lets the peak dominate everything else.

Two decisions that matter more than the fit:

- **Subject-level bootstrap**, not row-level. Resampling rows treats seven
  visits from one participant as seven independent observations; they are not,
  and the confidence interval comes out far too narrow. Resampling *subjects*
  with replacement preserves the correlation structure.
- **Refusal below 4 distinct timepoints.** A four-parameter curve through three
  points always fits, and always lies. The series is returned with
  `identifiable=False` and the dashboard plots the points alone, saying so.

### 4.3 Retrieval — `search.py`

- **BM25** hand-written in ~30 lines (`k1=1.5`, `b=0.75`) — readable, no dependency.
- **Dense retrieval** via Ollama embeddings when available, cached to disk and
  **flushed after every batch** so an interrupted run keeps the work it paid for.
- **Reciprocal Rank Fusion**: `score(d) = Σ_r 1/(60 + rank_r(d))`. Parameter-light,
  and it needs no score calibration between two retrievers on different scales.
- **Kind weighting** (`finding` 1.0, `abstract` 0.45). An abstract contains every
  claim of a paper at once, so it wins on raw lexical overlap and buries the
  precise finding that should be cited. Down-weighting restored the intended
  ranking: recall@3 0.667 → 0.792.
- **A conservative, idempotent stemmer.** Without it, *"compared across different
  trials"* matched none of the findings about *"cross-trial comparability"* —
  the project's most central query scored **0.00**. Idempotence is the part
  that is easy to get wrong: one pass turned "response" into "respons", a
  second into "respon", and a stemmer whose output depends on how many times it
  ran breaks every match where one side was stemmed twice. It iterates to a
  fixed point.

### 4.4 Quote verification — `extract.py`

The anti-hallucination mechanism, and the place where a naive threshold fails.

A quote is accepted only if **both** hold against the source text:

1. character similarity ≥ **0.97**, and
2. an **identical content-word multiset**.

The second condition exists because of a measured failure: *"did not induce"* →
*"did induce"* scored **0.95** and passed a 0.92 threshold. A single-word
negation flip is where hallucination actually hides, and it is nearly invisible
to character similarity. Detection went from 94% to **100%** on 144 corrupted
quotes, with zero loss on the 40 real ones.

An anchor prefilter (longest rare words first) makes the common case — a quote
that is *not* in the source — about 460× faster.

### 4.5 Bayesian D-optimal design — `optimal_design.py`

Which sampling days, given a visit budget? Greedy maximisation of
`E_θ[log det FIM]` over candidate days, with the kinetic prior drawn from the
scenario's platform.

Stated honestly in the output: the chosen days are only as good as that prior,
and the prior is an illustrative assumption. The design is presented as a
proposal, with the alternatives and the criterion value shown.

### 4.6 The agent — `agent.py`

A bounded state machine, not a framework:

```
parse → propose → retrieve → critique → (revise ×1) → report
```

`critique` runs **7 objective self-checks** (budget respected, baseline present,
late visit for a durability question, evidence coverage, …). `revise` runs **at
most once** and fixes only what is mechanically fixable. Every transition is
appended to a log that the dashboard displays verbatim.

`run_agent(..., use_llm=False)` pins the deterministic parser — which any test
of the agent's own logic needs, because otherwise the result depends on which
optional models the machine happens to have (§6.3).

### 4.7 Table 1 — `consortia.py`

The only non-synthetic measurement data in the project: six consortia from the
2026 workshop report (COMMUNITY, GERMINATE, MOVE, MUSICC, Project NextGen,
VAXXAIR), transcribed cell by cell with the verbatim text kept beside this
project's interpretation.

A consortium is not a measurement — VAXXAIR samples three upper-airway sites,
one lower-airway site and runs two assay families, and *"Humoral response
(IgG/IgA titres)"* is two measurements written as one cell. So the six expand
into **38 measurement contexts**, and 7 cells that cannot be represented
(environmental sampling, viral PCR, single-cell RNA-sequencing) are recorded
with a reason rather than dropped.

**Result over 561 cross-consortium pairs: not one is fully comparable.**

- **547** are ruled out by something Table 1 *does* record — a different
  compartment, device, isotype or assay.
- **14** agree on everything recorded, so whether those numbers may be compared
  is decided entirely by the five fields the table does *not* record: **unit,
  normalisation, assay floor, antigen, laboratory**.

The model had to grow to hold real data: a `lower_airway` compartment and six
sampling methods (mid-turbinate swab, NALT biopsy, tonsil, BAL, bronchosorption,
PExA). **The rule engine needed no change** — it compares method identity rather
than consulting a hard-coded table. That is the useful signal about the design.

---

## 5. Evaluation

`python -m mvc.eval.run` — 8 gating metrics, thresholds that fail CI:

| Metric | Value | Threshold |
|---|---|---|
| retrieval_recall@3 | 0.770 | ≥ 0.700 |
| retrieval_recall@5 | 0.863 | ≥ 0.800 |
| retrieval_mrr | 0.843 | ≥ 0.600 |
| extraction_true_acceptance | 1.000 | ≥ 0.950 |
| extraction_fake_detection | 1.000 | = 1.000 |
| comparability_accuracy | 1.000 | = 1.000 |
| kinetics_peak_rel_error | 0.115 | ≤ 0.350 |
| kinetics_ci_coverage | 1.000 | ≥ 0.700 |

(BM25-only figures. With embeddings pulled: recall@3 0.804, MRR 0.971.)

**Gating runs on the curated base only.** The merged corpus, which includes
`extracted_evidence.json`, is reported as *informational*. That file is
gitignored because it is reproducible, and a threshold that depends on a file
not under version control gives different verdicts on different machines —
which it did, once, failing by 0.001.

---

## 6. Engineering decisions worth defending

### 6.1 Synthetic data is the test bench, not a placeholder

The generator does not produce "some data". It simulates a **subject-level
truth** — three correlated antibody responses per participant — then
deliberately corrupts it six ways: lavage dilution ×0.1, inter-lab bias ×1.3,
unit scaling ×1000, LLOQ censoring, two-fold titre snapping, missing visits.

The comparability engine never sees the truth. So when it reports that lavage
and nasosorption are not comparable, that verdict can be **checked against a
known answer** — which is what `comparability_accuracy = 1.000` on 13 labelled
pairs measures. Synthetic data is the only setting where ground truth exists.

### 6.2 Everything degrades, nothing breaks

Every AI-assisted step has a deterministic fallback, and the dashboard reports
**per role** which path is live. A 3B model on a CPU laptop is not a dependency
to put on a critical path.

### 6.3 Three defects the honest version of this document should name

1. **A stub that invented an API.** Plotly could not be installed in the build
   environment, so figure tests ran against a local stand-in exposing `fig.ann`
   and `fig.lines` — attributes plotly has never had. Two regression tests
   passed locally, proved nothing, and failed in CI. A stub whose API differs
   from the real thing does not reduce risk, it hides it. The stub now mirrors
   plotly.
2. **A CI that had never been run.** `ruff` was not installed in the build
   environment, so the lint step ran for the first time on GitHub: 34 findings.
   Shipping a CI configuration without running it is the same mistake as
   shipping a test that never fails.
3. **A test whose result depended on installed models.** It passed with no text
   model and failed with `qwen2.5:3b` present — because the model read *"3
   visits"* as `max_visits: 6`, the value from the example in its own prompt. No
   contradiction left, no revision, test fails. Hence `use_llm` (§4.6).

The third is also the most interesting *finding*: on an explicit number next to
its noun, the keyword rules are not merely adequate, they are **better** — they
cannot hallucinate a value they did not see. That is the honest basis for the
architecture: **rules on the critical path, model as an option on top.**

### 6.4 Two display bugs a user found by reading

- The kinetics legend named the arm *and* the series and showed only the first
  panel's entries, so a five-panel figure carried two keys, both saying
  `nasal_wash`, while four panels went unlabelled.
- The legend's `y` offset is a *fraction* of figure height, so the −0.2 that
  sits neatly under one 320 px panel opened a 320 px hole under a 1600 px one.
- An annotation's `y` on a log axis is the **exponent**: passing a raw 218 000
  asked for 10^218000, and the axis grew to 10^112, flattening every real curve
  in that panel.

All three lint clean, pass every unit test, and are obvious to anyone looking at
the screen. Figures now have tests that assert on their own coordinates.

---

## 7. Reproducing

```bash
pip install -e ".[all]"
python -m mvc.cli doctor      # what is installed, what is missing
python -m mvc.cli demo        # objectives 1-6 end to end -> outputs/
python -m mvc.cli dashboard   # the dashboard
ruff check src tests app scripts
pytest -q                     # 199 tests
python -m mvc.eval.run        # 8 gating metrics
```

CI (`.github/workflows/ci.yml`) runs exactly these, on Python 3.10 and 3.12,
plus an **evidence-integrity gate**: every quote in the evidence base is
re-verified against its source, and any citable study without a DOI or PMID
fails the build.

### Container

```bash
docker compose up     # then http://localhost:8501
```

~400 MB image, Python 3.12-slim. The Ollama models are deliberately **not**
baked in — gigabytes, optional everywhere, and the compose file reaches a host
Ollama through `host.docker.internal` if one is running. `data/incoming/` is
mounted **read-only**: the app can read a user's CSV, never change it.

---

## 8. Scope

Not clinical advice. Not a medical device. Not a trial protocol. No patient
data, no partner data, no confidential material. Public literature and
synthetic data only. The author is a software/AI architect, not an
immunologist: everything requiring domain judgement is surfaced as an open
question rather than answered. See [LIMITS.md](LIMITS.md).
