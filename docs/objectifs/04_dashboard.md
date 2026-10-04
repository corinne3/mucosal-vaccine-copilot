# Objective 4 — Dashboard with uncertainty and non-comparability

> *"a dashboard comparing mucosal and systemic kinetics while flagging uncertainty and non-comparable measurements"*

**Modules:** `src/mvc/comparability.py`, `src/mvc/kinetics.py`, `src/mvc/figures.py`,
`app/dashboard.py` · **Tests:** 25 + 15 · **Run:** `python -m mvc.cli dashboard`

This is the core of the project. The other five objectives support it.

---

## The reading of the brief

The brief says *comparing … while flagging … non-comparable measurements*. Those two
clauses are in tension, and resolving it is the whole design:

**You cannot both put two numbers on one axis and warn that they are not comparable.** A
warning under a misleading chart does not undo the chart — people read pictures, not
captions. So the dashboard does not warn. **It refuses.**

Non-comparable series are routed into separate panels, and the only place compartments
meet is a view where the quantity itself is comparable: fold-rise over each subject's own
baseline.

## 1. The comparability engine

10 rules, each a small pure function returning at most one flag with a code, a human
message and a **remedy**. Severity is the maximum over flags, on three levels:

| Level | Meaning | Effect on the figures |
|---|---|---|
| `comparable` | same context throughout | may share an absolute axis |
| `conditional` | comparable with a caveat | shares an axis, caveat shown |
| `not_comparable` | different quantities | **never** on one absolute axis |

The rules, in order from most to least structural:

| Rule | Verdict | Why |
|---|---|---|
| different compartment | not comparable | compartmentalised responses; absolute scales unrelated |
| mucosal device mismatch | not comparable, **unless** both normalised to total IgA → conditional | lavage dilutes by an unknown factor, absorptive strips do not |
| different assay | not comparable | binding and functional readouts measure different things |
| different isotype | not comparable (IgA vs sIgA → conditional) | sIgA is a subset of IgA |
| different normalisation | not comparable | different quantities entirely |
| different unit | not comparable; convertible pairs → conditional | `au_ml` is lab-specific by definition |
| different antigen | conditional | cross-reactivity, not the same response |
| different lab | conditional | inter-lab bias is common for mucosal assays |
| digitised from a figure | conditional | approximate by construction |
| synthetic vs measured | not comparable | never mix fabricated and real data |

**The middle level is what makes the tool usable.** "Different labs" is a real caveat but
not a reason to hide data; a boolean verdict would force every caveat into silence or
refusal.

**Why rules and not a model.** A reviewer must be able to disagree with a *specific rule*
rather than with "the model". 13 labelled pairs pin the entire engine
(`eval/run.py::COMPARABILITY_CASES`), accuracy is a thresholded CI metric at 1.00, and
every `not_comparable` flag is required by test to carry a remedy
(`test_every_flag_has_message_and_remedy`).

Three API surfaces: `compare(a, b)` for one pair, `comparability_matrix(df)` for all
pairs, `audit_table(df)` for series-level data quality.

## 2. Kinetics with honest uncertainty

**Model** — the Bateman function, borrowed from pharmacokinetics:

```
y(t) = b + A·(e^{-ke·τ} − e^{-ka·τ}),   τ = max(t − lag, 0),   ka > ke
t_peak = lag + ln(ka/ke)/(ka − ke)
half-life = ln2 / ke
```

Four interpretable parameters, one per question the brief asks: baseline (prior immunity),
amplitude, time to peak, durability.

**Three deliberate choices:**

1. **Residuals on log10.** Antibody noise is multiplicative; fitting on the raw scale would
   let the peak dominate and distort the tail.
2. **Subject-level bootstrap**, not row-level. Repeated measures on one participant are
   correlated, so resampling rows would understate uncertainty — the one error this project
   must not make. Resample participants, refit, take percentiles.
3. **Refusal to fit what cannot be fitted.** Fewer than 4 distinct timepoints for a
   4-parameter model → `identifiable=False`, medians returned with a note, no curve drawn.
   A tool that reports a half-life from three points is worse than no tool
   (`test_fit_declares_itself_unidentifiable_on_sparse_data`).

**Self-diagnosis.** The fit adds its own notes: *"Half-life poorly constrained: not enough
late timepoints"*, *"Peak day uncertain (95% CI wider than 3 weeks): add sampling around
the peak"*, *"Half-life extrapolated far beyond last sample"*. Those notes are what feed
roadmap tasks.

**Graded, not eyeballed.** Because the synthetic generator knows the truth, the fit is
measured: relative error on peak day **0.12**, bootstrap CI coverage **8/8** — both
thresholded in CI.

## 3. Fold-rise: the only cross-compartment scale

```python
fold_rise = value / subject's own day-0 value, per (subject, series)
```

Note **per (subject, series)**, not per subject. One participant contributes several series
(nasal and serum, two labs, two units), so a subject-only baseline is ambiguous — and
dividing a serum value by a nasal baseline is exactly the category error this project
exists to prevent. This was a real bug the test suite caught
(`test_fold_rise_is_relative_to_own_baseline` crashed on a non-unique index), and the fix
made the semantics explicit.

This is also why a day-0 sample is non-negotiable in objective 3: without it, the only
legitimate cross-compartment comparison is unavailable.

## 4. Figures that obey the verdicts

`figures.py` enforces, rather than decorates:

- `split_comparable_groups` greedily partitions series so that each facet contains only
  mutually comparable (or conditional) series. **One panel per group** — the layout itself
  carries the verdict.
- Every fitted curve gets its bootstrap band; an unidentifiable fit is drawn as **points
  only** with a visible note.
- Values below LLOQ use open markers — never drawn as if measured.
- Colour-blind-safe Okabe–Ito palette, used systematically: one colour per compartment, one
  dash pattern per sampling device.

Five figures: kinetics (faceted), fold-rise (the shared scale), comparability heatmap,
data-quality bars, visit schedule.

## 5. The dashboard

Seven tabs mapping to objectives: **Scenario** (3), **Kinetics** (4),
**Comparability** (4), **Uncertainty** (4), **Evidence** (2), **Roadmap** (6),
**Quality** (evals).

On the demo dataset: 6 series, **14 non-comparable pairs flagged**, each expandable to its
reasons and remedies. The sidebar states the retrieval mode and whether a local LLM is
reachable — capability is disclosed, not hidden.

Accepts an uploaded CSV as well as the synthetic data, validates the required columns, and
fills optional context columns with explicit defaults.

## Uncertainty, in four distinct senses

The brief says "flagging uncertainty". The tool separates four things that are usually
conflated:

| Kind | Where it surfaces |
|---|---|
| **Statistical** — how precise is this estimate? | bootstrap CIs on peak day and half-life |
| **Structural** — can this quantity be estimated at all? | `identifiable=False`, points-only rendering |
| **Data quality** — is the input adequate? | `audit_table`: thin series, LLOQ censoring, missingness, no baseline |
| **Semantic** — do these numbers mean the same thing? | the comparability engine |

The fourth is the one conventional pipelines lose entirely, and it is the one that produces
confidently wrong charts.

## Known shortcuts

- LLOQ values imputed at LLOQ/2 — biases means downward; a censored-data likelihood is a
  generated roadmap task.
- Greedy grouping of comparable series is not a minimal partition.
- The 4-fold line on the fold-rise plot is labelled *"conventional threshold — confirm with
  the expert"* rather than asserted as a criterion.

## Checks

```bash
python -m mvc.cli demo          # writes the matrix, the audit and the HTML figures
python -m mvc.cli dashboard
pytest tests/test_comparability.py tests/test_kinetics_and_synthetic.py -q
```
