# Demo script — what to type, and what it should show

Three text boxes accept free text: **Scenario**, **Evidence → Search**, and
**Roadmap → Scenario**. This file gives sentences to paste into each, with the
expected result beside it, so a demo can be rehearsed and a failure recognised.

A note before anything else, because it is the question every technical
audience asks and the honest answer is not the flattering one:

> **A free-text box does not imply a language model.** By default the Scenario
> box is read by a keyword parser — roughly sixty lines of `if` statements —
> and the Evidence box by BM25, a 1994 ranking function implemented here in
> about thirty lines. Both are deterministic, both run in milliseconds, and
> neither needs a model to be pulled. The local LLM is an *option* on every
> one of these paths, never a requirement. The "Rules vs local LLM" panel in
> the Scenario tab exists so that an audience can watch the two disagree
> rather than take this claim on trust.

---

## 1. Scenario tab

### 1a. The baseline — it should just work

```
Phase 1 comparison of an intranasal live-attenuated influenza vaccine against
the injected inactivated vaccine in 40 healthy adults, 7 visits maximum over
180 days. We care about the peak, durability and the mucosal versus systemic
comparison.
```

Expect: **40 participants, 7 visits** read straight off the sentence, ~10 candidate options, 8 evidence-backed and 2
marked `ASSUMPTION`, self-check **pass**.

### 1b. Children — a different population changes the plan

```
Intranasal live-attenuated influenza vaccine in 120 children aged 2 to 8,
maximum 4 visits because the parents will not come back more often, 90 days of
follow-up. We mainly want to know the peak.
```

Expect: **120 participants, 4 visits, paediatric population detected**, and at least one option whose rationale changes on the
paediatric population. Watch the visit count drop — the design is constrained by
what you said, not by a template.

### 1c. The one that exposes a limit — use this one deliberately

```
We want to know whether nasal IgA protects against infection.
```

Expect: the plan still appears, but the **open questions** section says the
correlate of protection is an expert decision this tool refuses to make. This
is the demo's best moment: the honest answer to the most important question is
"I will not answer that", and it is in the code, not in a disclaimer.

### 1d. Deliberately sparse — watch it refuse to invent

```
A nasal vaccine. 12 people. 2 visits.
```

Expect: a plan with very few options, more `ASSUMPTION` flags, and a self-check
that may **FAIL**. A failing self-check on a thin scenario is the tool working.

### 1e. For the "Rules vs local LLM" panel

Run the comparison on **1a** first: the two parsers should agree on every
field, which is the argument for keeping the rules on the critical path — same
answer, no model, no wait.

Then run it on this, which is written to break keyword matching:

```
This is not an injected study. Participants receive the vaccine through the
nose. We plan to enrol four dozen grown-ups and see them on seven occasions
across half a year.
```

Expect disagreement: the rules key on literal words, so "four dozen" and "half
a year" are invisible to them, and "not an injected study" may be read as
*injected* because the keyword matcher does not see negation. That is where a
model earns its place — not on ordinary sentences, but on negation,
spelled-out numbers and unusual phrasing.

**But do not promise that the model wins.** It was measured, and the result cut
both ways. Asked for a JSON scenario from

```
intranasal adenovirus covid vaccine, 3 visits, 90 days follow up, durability
```

`qwen2.5:3b` returned `max_visits: 6` — the value from the example in its own
prompt — for a sentence that plainly says *3 visits*. The keyword rules read 3.
On an explicit number next to its noun, the rules are not merely adequate, they
are **better**: they cannot hallucinate a value they did not see.

Run that sentence through the panel too. A demo where the model is shown losing
a round is worth more than one where it always wins, and it is the honest basis
for the architecture: **the rules are on the critical path, the model is an
option on top of them.**

> Without `qwen2.5:3b` pulled, the panel says so and shows the rules alone.
> `ollama pull qwen2.5:3b` enables it (≈2 GB).

---

## 2. Evidence tab — search

These run against the verified evidence base (7 citable studies, 40 findings).

| Type this | Expect |
|---|---|
| `does nasal IgA correlate with serum IgG?` | findings about compartmentalisation; the two are weakly correlated |
| `how should samples be compared across different trials?` | the cross-trial comparability findings — this is the project's most central query, and it scored **0.00** before stemming was added |
| `nasosorption versus nasal lavage dilution` | the device/dilution findings that justify the whole comparability engine |
| `do all participants respond to the vaccine?` | the responder-fraction findings — this one works because of a hand-written synonym entry, since "respond" and "response" stem to different roots |
| `tuberculosis vaccine schedule` | **few or no good hits.** Use it. An evidence base of 7 studies has edges, and showing one is more convincing than pretending it does not |

Tick **Citable sources only** to watch the unverified placeholder studies drop
out of the results.

---

## 3. Roadmap tab

Same sentences as the Scenario tab. The roadmap is generated from *that run's
own gaps* — unsupported options, failed self-checks, thin series, non-comparable
pairs — so **1d** ("A nasal vaccine. 12 people. 2 visits.") produces a visibly
longer roadmap than **1a**. Run both back to back; that contrast is the point.

---

## 4. Consortia (Table 1) — nothing to type

Three numbers to say out loud:

- **38** measurement contexts from 6 real consortia
- **561** cross-consortium pairs, **none** fully comparable
- **14** of them blocked only by metadata the published table does not record

And the optimistic one, which belongs first: **6 consortia out of 6 already use
nasosorption.** The devices have converged; the reporting has not.

---

## 5. If a demo goes wrong

| Symptom | Cause | Say this |
|---|---|---|
| Sidebar shows models "not pulled" | normal; nothing is pulled by default | "every AI step has a deterministic fallback, and it is running" |
| A panel says "fit not identifiable" | fewer than 4 distinct timepoints | "it refuses to fit a 4-parameter curve to 3 points — that is the feature" |
| Search returns nothing useful | the evidence base is 7 studies | "that is a seed, not a systematic review, and the README says so" |
| An option is flagged `ASSUMPTION` | no quote supports it | "it labels its own unsupported claims instead of phrasing them as fact" |
