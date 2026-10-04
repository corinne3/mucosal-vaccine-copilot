# Mucosal Vaccine Copilot

**Transparent, evidence-traced design support for mucosal (intranasal) vaccine trials.**

Personal learning project. Built on **public literature and synthetic data only**.
It produces *candidate measurement options for review by qualified domain experts* —
it is **not clinical advice**, not a trial protocol, and it designs nothing by itself.

---

## The one idea

Two antibody numbers are only comparable if they were produced the same way.

A nasal IgA value from a lavage and one from an absorptive strip are not on the same
scale (lavage dilutes the sample). A serum IgG and a nasal IgA are not on the same
scale at all (the compartments are separate). Put them on one axis and the chart lies
— confidently, and in a way a reader cannot detect.

So this project refuses to. Every measurement carries its full **measurement context**
(compartment, sampling device, isotype, assay, unit, normalisation, laboratory, data
provenance), a rule engine decides what may be compared with what, and the dashboard
is *forbidden* from drawing non-comparable series on a shared absolute axis.

The same principle governs the text side: every recommendation must point at a
**verbatim quote** from a real paper, and a quote that cannot be found in its source
is dropped automatically. What remains unsupported is labelled `ASSUMPTION` in red
rather than quietly phrased as fact.

> This is the same problem I worked on professionally — automated **coherence
> validation** across heterogeneous technical documents — moved to a scientific domain.
> There, the question was whether two railway folios contradict each other. Here, it is
> whether two antibody measurements can be compared at all. The machinery is the same:
> make the context explicit, make the rules readable, refuse to merge what cannot be
> merged, and never assert what you cannot trace.

---

## The six objectives

The HackLab brief for this track asks for six things. Each maps to a module, a document
and tests.

| # | Objective | Module | Doc |
|---|---|---|---|
| 1 | Structured model: trial design, nasal sampling, immune endpoints, kinetics | `mvc/schema.py` | [01](docs/objectifs/01_modele.md) |
| 2 | Small evidence base from representative published studies | `mvc/evidence/` | [02](docs/objectifs/02_preuves.md) |
| 3 | Prototype: trial scenario in → transparent sampling & endpoint strategy out | `mvc/strategy/` | [03](docs/objectifs/03_strategie.md) |
| 4 | Dashboard comparing mucosal vs systemic kinetics, flagging uncertainty and non-comparable measurements | `mvc/comparability.py`, `mvc/kinetics.py`, `mvc/figures.py`, `app/dashboard.py` | [04](docs/objectifs/04_dashboard.md) |
| 5 | Demonstration on a public respiratory-vaccine case + synthetic data | `mvc/synthetic.py` | [05](docs/objectifs/05_demo.md) |
| 6 | 90-day validation and IP roadmap | `mvc/roadmap.py` | [06](docs/objectifs/06_roadmap.md) |

Beyond the brief (the "more techniques" part):

| Extra | What it adds | Module |
|---|---|---|
| Knowledge graph | studies ↔ methods ↔ compartments ↔ tags; answers "what supports this?" and "what is missing?" | `mvc/evidence/graph.py` |
| Hybrid retrieval | BM25 (hand-written) + embeddings, fused with Reciprocal Rank Fusion | `mvc/evidence/search.py` |
| Structured extraction | local LLM with JSON-schema-constrained decoding, plus a deterministic fallback | `mvc/evidence/extract.py` |
| Quote verification | catches single-word meaning flips, which is where hallucination actually hides | `mvc/evidence/extract.py` |
| Bayesian D-optimal design | picks sampling days by maximising Fisher information | `mvc/strategy/optimal_design.py` |
| Agent with self-critique | parse → propose → retrieve → critique → (revise once) → report | `mvc/strategy/agent.py` |
| Bootstrap uncertainty | subject-level resampling; says when a curve is *not* identifiable | `mvc/kinetics.py` |
| Figure digitisation | vision model reads data points off a published plot, flagged as approximate | `mvc/figure_digitizer.py` |
| **Real-world case** | Table 1 of the workshop report: 6 ongoing consortia, 38 measurement contexts, every pair run through the engine | `mvc/consortia.py` |
| MCP server | the same engines as tools for Claude Desktop / Claude Code | `mvc/mcp_server.py` |
| Eval harness | 8 gating metrics + 2 informational, thresholds that fail CI | `mvc/eval/` |
| CI | lint, 198 tests, evals, demo, evidence-integrity gate | `.github/workflows/ci.yml` |

---

## Quick start

**Not a developer?** Install [Docker Desktop](https://www.docker.com/products/docker-desktop/),
then `docker compose up` and open <http://localhost:8501>. Nothing else is
installed on the machine. See [RUN_ME_WINDOWS.txt](RUN_ME_WINDOWS.txt).

**From source:**

```bash
git clone <this repo> && cd mucosal-vaccine-copilot
pip install -e ".[all]"

python -m mvc.cli doctor      # what is installed, what is missing
python -m mvc.cli demo        # objectives 1-6 end to end -> outputs/
python -m mvc.cli dashboard   # the Streamlit dashboard (walkthrough: docs/MANUEL_DASHBOARD.md,
                              # demo script: docs/DEMO.md)
pytest -q                     # 198 tests
python -m mvc.eval.run        # 8 gating metrics against thresholds
```

**Before travelling**, with network:

```bash
python scripts/download_pack.py
```

That installs dependencies, builds an offline pip wheelhouse, downloads the papers and
trial registrations into `data/raw/`, pulls the Ollama models, warms the embedding
cache, then runs tests + evals + demo as a final check. After it, everything works
with the wifi off.

---

## Everything works without an LLM

Each AI-assisted step has a deterministic fallback, because a 3B model on a CPU laptop
in a train is not a dependency you want on the critical path:

| Step | With a local LLM | Without |
|---|---|---|
| Scenario parsing | JSON-schema-constrained extraction | keyword parser (`parse_scenario_rules`) |
| Paper extraction | structured, quote-verified | verbatim-sentence extraction by regex |
| Retrieval | BM25 + embeddings, RRF-fused | BM25 only (recall@3 0.77, recall@5 0.86 on the gold set) |
| Figure digitisation | vision model | unavailable — and it says so |
| Explanations | narrative text | the rule engine's own rationale strings |

No API keys, no credits, no data leaving the machine. Models run through
[Ollama](https://ollama.com); defaults are `qwen2.5:3b`, `nomic-embed-text`,
`qwen2.5vl:3b` (override with `MVC_LLM_MODEL`, `MVC_EMBED_MODEL`, `MVC_VLM_MODEL`).

---

## What it looks like

```
$ python -m mvc.cli propose "intranasal LAIV vs injected IIV in 40 adults, 7 visits, durability"

visits [0, 3, 7, 28, 42, 120, 180] · coverage {'options': 10, 'evidence_backed': 8, 'assumptions': 2}
self-check pass
-> outputs/strategy.md
```

The briefing marks each option as either evidence-backed (with the quote) or
`ASSUMPTION — no supporting evidence`, and ends with the list of decisions it refuses
to make: endpoint ranking, sample size, device acceptability, correlates of protection.

---

## Repository layout

```
src/mvc/
  schema.py              objective 1 — the domain model, with validators that refuse incoherent designs
  comparability.py       the rule engine: may A and B be compared?
  kinetics.py            Bateman curve fitting + subject-level bootstrap
  synthetic.py           objective 5 — synthetic generator that injects the heterogeneity to be caught
  figures.py             objective 4 — plotly figures that obey the comparability verdicts
  roadmap.py             objective 6 — roadmap derived from the run's own gaps
  figure_digitizer.py    option — vision model reads a published figure
  mcp_server.py          option — MCP adapter
  llm.py                 minimal Ollama client (stdlib only)
  cli.py                 one command per objective
  evidence/              objective 2 — fetch, ingest, extract, verify, search, graph
  strategy/              objective 3 — rules, optimal design, agent
  eval/                  option — measured, thresholded evaluation
app/dashboard.py         objective 4 — Streamlit
data/evidence/           the verified evidence base (JSON, hand-checked quotes)
data/eval/               retrieval gold set
docs/                    architecture, per-objective notes, domain primer, train plan
tests/                   198 tests
scripts/download_pack.py run at home before the train
```

---

## Honest limitations

- The seed evidence base holds **7 citable studies** and 40 verified findings — one of
  which is the field's own 2026 consensus workshop report, which is why the project's
  comparability rules can be traced to something other than my own reading. That is a
  seed, not a systematic review. Four more studies are present as `to_verify`
  placeholders and are **not citable** until their abstracts are retrieved.
- The synthetic generator's parameters are **illustrative assumptions** reproducing
  qualitative patterns, not estimates of any real vaccine.
- The D-optimal design is only as good as its kinetic prior, which is one of those
  assumptions.
- The retrieval gold set has 17 hand-judged queries. Small, but real.
- The Table 1 analysis compares **how six consortia measure**, never what they
  measured — those trials have published no values. Five of the ten fields the
  engine needs are absent from the table, so no cross-consortium pair can ever
  come back fully `comparable`. That is the finding, not a limitation of the
  engine, but it does mean the tab reports an upper bound on comparability.
- The author is a software/AI architect, not an immunologist. Everything requiring
  domain judgement is surfaced as an open question rather than answered.

## Scope

Not clinical advice. Not a medical device. Not a trial protocol. No patient data, no
partner data, no confidential material. See [docs/LIMITS.md](docs/LIMITS.md).

## Licence

MIT. Quoted abstracts belong to their publishers and are cited with DOI/PMID.
