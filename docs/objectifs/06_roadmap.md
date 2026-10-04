# Objective 6 — 90-day validation and IP roadmap

> *"a 90-day validation and IP roadmap"*

**Module:** `src/mvc/roadmap.py` · **Tests:** part of `tests/test_strategy_and_roadmap.py` ·
**Run:** `python -m mvc.cli roadmap "..."` → `outputs/roadmap.md`, `outputs/roadmap.csv`

---

## The design decision

A hand-written roadmap is a wish list. It says what you *intend* to do, which is unrelated
to what the project actually needs.

So this one is **generated from the run's own results**. Every task traces back to a gap
the pipeline detected, and the `origin` field names that gap:

| Detected gap | Generated task | Owner |
|---|---|---|
| An option with no supporting evidence | "Validate or reject: *option*" | domain expert |
| An open question raised by the rules | "Resolve: *question*" | matched by keyword |
| A failed self-check | "Fix: *issue*" | project lead |
| `to_verify` placeholder studies | "Retrieve and verify N placeholder studies" | data engineer |
| Non-comparable series pairs in the data | "Reduce the N non-comparable pairs" | lab lead |
| Series with fewer than 4 timepoints | "Add timepoints to N thin series" | clinical trial expert |
| Values below LLOQ | "Pre-specify the LLOQ handling" | biostatistician |
| A half-life whose bootstrap CI is 5× the estimate | "Add a late visit for *series*" | clinical trial expert |

**The consequence that matters:** the roadmap cannot claim a gap does not exist, because
the gap is what generated the task. On the demo scenario it produces **20 tasks** across
three months.

Ownership is assigned by keyword matching against the question text — sample size and power
go to the biostatistician, devices and assays to the lab lead, endpoints and regulatory
matters to the clinical trial expert, immunology and correlates to the mucosal
immunologist. Crude, and it means no task lands unassigned
(`test_roadmap_assigns_specialists_to_specialist_questions`).

Every task carries an **acceptance criterion**, not just a title — "Bootstrap CI of the
half-life narrows below a factor 3", "Self-check passes on the next pipeline run",
"100% of quotes confirmed verbatim". A task you cannot tell is finished is not a task.
Enforced by test: `all(t.acceptance and t.owner and t.origin for t in rm.tasks)`.

## Shape of the 90 days

- **Month 1 — make the foundations trustworthy.** Validate or drop every unsupported
  assumption. Complete the `to_verify` studies. A second reviewer re-checks every quote
  against its source: the automated check catches fabrication, not misinterpretation, and
  that distinction needs a human.
- **Month 2 — harden data and method.** Harmonise what is non-comparable, add timepoints to
  thin series, pre-specify the statistical handling, expand the evidence base through the
  same verification gate.
- **Month 3 — prove it works for someone else.** Real data replacing synthetic (synthetic
  kept as the test suite), reproducible environment with pinned versions and hashed data
  manifests, evals on an expanded gold set, the limits document, a dry run with the domain
  experts, then a written go / no-go that lists the assumptions still untested.

The most important task in the whole plan is the dry run: *"Experts can follow every
recommendation back to its source without help."* Transparency is the product's only
claim, so it is the thing to test on people who did not build it.

## The IP half: facts and questions, never conclusions

IP strategy is a qualified lawyer's call. The HackLab has a **patent attorney** on the
mentor list (Sara, UK & European Patent Attorney, synthetic biology and biotech), which is
precisely the person for this. So the module emits two lists and no advice.

**Established facts** — things that are simply true about this repository:

- The code is the author's own work, written on public and synthetic data only.
- The evidence base cites public literature; abstracts are quoted, not redistributed whole.
- Europe PMC and ClinicalTrials.gov content is used under their terms, each record keeping
  its identifier.
- No partner data, no confidential document, no third-party dataset.
- Open-weight models run locally; nothing leaves the machine at inference time.
- **Work produced inside a company-sponsored track belongs under that track's own
  agreement** — which is exactly why this repository is kept separate from it.

**Open questions for counsel:**

- Which parts, if any, are patentable rather than simply publishable?
- Does an open-source licence — and which — serve the project better than keeping it closed?
- If a partner's data is used later, what agreement must exist first?
- Are the licence terms of each model and dataset compatible with the intended use?
- Who owns contributions from other participants, and is that written down?

`test_roadmap_ip_section_states_facts_and_questions_only` checks both lists are non-empty
and that the generated markdown names the lawyer requirement.

## The separation that makes this usable at a hackathon

The last IP fact is a practical boundary, not legal caution. This repository was built
beforehand, on public and synthetic data, so:

- it is publishable regardless of what the track partner decides about their own work;
- it can be *offered* to the team as a starting point without entangling ownership;
- nothing the partner shows on site gets reverse-engineered back into it.

Asking the partner about IP and publication before writing a line with them is the first
item on the arrival checklist in `docs/TRAIN_PLAN.md`.

## Output

```bash
$ python -m mvc.cli roadmap "intranasal LAIV vs injected IIV in 40 adults, 7 visits, durability"
20 tasks -> outputs/roadmap.md, outputs/roadmap.csv
```

`roadmap.md` — month-by-month tables with id, task, owner, target week (real dates),
priority, acceptance criterion and origin; then the untested-assumption list, then the two
IP sections. `roadmap.csv` — the same, for a project tracker.

## Limitations

- Keyword-based ownership assignment will mis-assign unusual phrasings.
- Week numbers are a plausible ordering, not a resourced schedule — no capacity model, no
  dependencies between tasks.
- The task list is only as complete as the detectors. A gap the pipeline cannot see
  produces no task, which is why the human dry run exists.

## Checks

```bash
python -m mvc.cli roadmap
pytest tests/test_strategy_and_roadmap.py -q -k roadmap
```
