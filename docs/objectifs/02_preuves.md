# Objective 2 — Evidence base

> *"a small evidence base from representative published studies"*

**Modules:** `src/mvc/evidence/` (`store`, `fetch`, `ingest`, `extract`, `search`, `graph`) ·
**Tests:** `tests/test_evidence.py` (41) · **Data:** `data/evidence/seed_evidence.json`

---

## What is in it

| | Count |
|---|---|
| Studies, citable (abstract verified by hand on 2026-10-02) | **6** |
| Verified findings, each with a verbatim quote | **24** |
| Studies present as `to_verify` placeholders | 4 |
| Retrieval gold set queries (hand-judged) | 12 |

Small, and honestly labelled as small. The alternative — a hundred auto-scraped
"findings" nobody checked — would look more impressive and be worth less, because a single
unverifiable citation discredits the whole base.

## Structure: study → findings → quotes

```json
{
  "study_id": "bean2024_challenge",
  "citation": "Bean R, Giurgea LT, Han A, et al. Mucosal correlates of protection ... mBio. 2024.",
  "doi": "10.1128/mbio.02372-23",
  "abstract": "… full verbatim abstract …",
  "findings": [{
    "finding_id": "bean2024_f2",
    "statement": "Mucosal IgA and serum IgG are weakly correlated: one compartment cannot stand in for the other.",
    "quote": "Correlations between mucosal IgA and serum IgG against specific antigens were low, whether before or after challenge, suggesting a compartmentalization of immune responses.",
    "tags": ["compartmentalization", "mucosal_vs_systemic", "endpoint_choice", "paired_sampling"]
  }],
  "not_reported": ["nasal sampling method (in abstract)", "sampling days (in abstract)"],
  "level": "verified_abstract"
}
```

Three things to notice:

- **`statement` is our normalised claim; `quote` is the source's own words.** The claim may
  be a paraphrase; the quote may not. The separation is what makes verification possible.
- **`not_reported` is explicit.** A study that does not state its sampling device says so,
  rather than leaving a reader to assume. Gaps are data.
- **`tags`** are the join key to objective 3: a rule cites finding ids, and the knowledge
  graph indexes findings by tag.

## Pipeline

```
Europe PMC REST ─┐
ClinicalTrials.gov ─┼─> data/raw/ ─> ingest ─> Document ─> extract ─> verify_quotes ─> EvidenceBase
local PDFs ──────┘                              (LLM or rules)      (drops the unverifiable)
```

### fetch.py — stdlib only, by choice

`urllib` rather than `requests`, so the download step works on a bare Windows Python with
nothing installed. Sources:

- **Europe PMC** — search, abstracts, and open-access full text as JATS XML
- **ClinicalTrials.gov API v2** — registered designs, which is where *real* sampling
  schedules live

Everything is cached under `data/raw/` with a manifest, so every later step is offline.

### ingest.py — three input shapes, one `Document`

JATS XML section extraction, Europe PMC JSON records, and PDF text via PyMuPDF.
`parse_timeframe` converts registry prose into days: `"Day 0, 7 and 28"` → `[0, 7, 28]`,
`"6 months post-vaccination"` → `[180]`. Those parsed timepoints become the empirical
prior for objective 3's anchor visits — the schedule is grounded in what trials actually
did, not in a guess.

### extract.py — two extractors, one contract

**`extract_rules`** (no LLM, deterministic): selects *verbatim sentences* matching domain
keyword patterns. Because it is extractive, it cannot invent — the worst case is an
irrelevant sentence, never a fabricated one.

**`extract_llm`** (local model): JSON-schema-constrained decoding, with a system prompt
requiring an exact quote per finding and an explicit `not_reported` list. Richer, and
capable of lying — which is what the next section is for.

`extract()` picks the LLM when one is reachable and silently falls back otherwise.

## The part that matters most: quote verification

A generated claim is worthless unless it can be traced to its source. So every finding's
quote is checked against the source text, and **findings whose quote cannot be found are
dropped**, not flagged for later.

The first implementation used character similarity with a 0.92 threshold. The eval suite
caught it immediately — these all passed as "found in source":

| Source says | Fake quote | Similarity |
|---|---|---|
| `did not induce IgA production` | `did induce IgA production` | 0.95 |
| `had lower levels of IgA` | `had higher levels of IgA` | 0.92 |
| `mucosal IL-33 release` | `systemic IL-33 release` | 0.92 |

A single-word flip barely moves the character ratio and **inverts the meaning**. A
verification step that accepts those is worse than having none at all: it stamps a
fabrication as sourced.

The fix requires two conditions together:

1. high character similarity on the best-matching window (threshold raised to 0.97), **and**
2. an **identical multiset of content words** in that window.

Condition 2 is the real one. Condition 1 only exists to absorb typographic noise from PDF
extraction — ligatures, hyphenation, odd whitespace — not different wording.

Result: fake detection 94% → **100%** on 86 corrupted quotes, real quotes still accepted
at **100%**. Both are thresholded metrics in CI, so a regression fails the build.

The same check runs again inside the agent's self-critique (objective 3), so a tampered
quote is caught even if it enters the base by another route
(`test_critique_catches_a_tampered_quote`).

## search.py — hybrid retrieval

- **BM25**, hand-written in ~30 lines, with domain synonym expansion
  (`iga → siga, secretory, mucosal`). Hand-written so it can be explained rather than
  invoked.
- **Dense retrieval** via local embeddings, cached on disk so it survives going offline.
- **Reciprocal Rank Fusion**: `score(d) = Σ_r w · 1/(k + rank_r(d))`. No score calibration
  needed between retrievers, which is exactly why RRF is used in practice.

**One tuned parameter, and why.** Abstract chunks are weighted 0.45 against findings at
1.0. An abstract contains every claim of the paper at once, so it dominates lexical
overlap and masks the precise finding a recommendation needs to cite. Down-weighting
restores the intended ranking: **recall@3 0.67 → 0.79**, gold set untouched.

Without an embedding model the searcher degrades to BM25 only and *says so* in
`searcher.mode` — surfaced in the dashboard sidebar rather than hidden.

## graph.py — the knowledge graph

```
study ──TESTS──> platform ──GIVEN_BY──> route
  │──USES_METHOD──> method
  │──MEASURES──> compartment
  │──USES_ASSAY──> assay
  └──REPORTS──> finding ──ABOUT──> tag
```

88 nodes, 155 edges on the seed base. Three queries earn it:

- `studies_for_tag(g, "compartmentalization")` → which studies support a claim
  (`citable_only=True` excludes `to_verify`, verified by test)
- `methods_for(g, platform, route)` → which devices were used for *this kind* of vaccine
- **`coverage_gaps(g)`** → platform × method combinations **no** study covers. Knowing
  where the evidence is absent is as useful as knowing where it is present, and it feeds
  the roadmap.

## Honest limitations

- Six citable studies is a seed, not a systematic review, and not assembled by a
  reproducible search strategy.
- Four `to_verify` placeholders remain because their abstracts could not be retrieved when
  the base was built (PubMed served a CAPTCHA). They are non-citable and generate a
  roadmap task.
- Findings come from abstracts, not full texts, so methodological detail is often
  `not_reported`.
- The gold set has 12 queries — real, but a wide confidence interval.

## Checks

```bash
python -m mvc.cli search "does nasal IgA correlate with serum IgG"
python -m mvc.cli graph
python -m mvc.cli download && python -m mvc.cli build-evidence   # needs network
pytest tests/test_evidence.py -q
```

`test_every_finding_quote_is_in_its_abstract` is the integrity gate: it also runs in CI, so
the base cannot drift into citing text its sources do not contain.
