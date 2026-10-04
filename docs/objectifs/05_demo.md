# Objective 5 — Demonstration on a public case + synthetic data

> *"a demonstration using one public respiratory-vaccine case and synthetic data"*

**Module:** `src/mvc/synthetic.py` · **Tests:** `tests/test_kinetics_and_synthetic.py` (15) ·
**Run:** `python -m mvc.cli demo`

---

## The public case: intranasal live-attenuated influenza vaccine vs injected inactivated

Chosen because it is the clearest illustration of the project's thesis, and because both
sides are documented in the evidence base:

| | Intranasal live-attenuated | Injected inactivated |
|---|---|---|
| Mucosal IgA | the intended effect | little or none — *"the conventional parenteral influenza vaccine did not induce IgA production in saliva"* (Tsunetsugu-Yokota 2022) |
| Serum response | often weaker — *"Systemic responses to intranasal vaccination were typically weaker than after intramuscular vaccination"* (Madhavan 2022) | strong — *"predominantly boosting serum antibody titers against hemagglutinin"* (Bean 2024) |
| Compartments | *"distinct, compartmentalized, antibody responses in the mucosa and blood"* (Thwaites 2023) | *"Correlations between mucosal IgA and serum IgG … were low"* (Bean 2024) |

**Why this comparison makes the point:** judge each vaccine in the compartment it is
designed to act on. A serum-only evaluation of a nasal vaccine measures the wrong thing
and calls it a failure. That is a measurement error, not a biological result — and it is
the error the tool exists to prevent.

The real trial registrations behind the demo (NCT04110366, NCT05522335) are downloaded by
`python -m mvc.cli download`, and their reported timepoints feed objective 3's anchors.

---

## The synthetic data

> **Every number produced by this generator is fabricated.** Parameter values are
> *illustrative assumptions* chosen to reproduce qualitative patterns reported in the
> literature. They are **not** estimates of any real vaccine and must never be presented as
> such. Every row carries `source="synthetic"`, and the comparability engine refuses to mix
> synthetic rows with measured ones.

### Why synthetic data at all

Three reasons, in order of importance:

1. **No real individual-level mucosal kinetics are publicly available** at the granularity
   this tool needs. Published papers give figures, not subject-level tables.
2. **Truth is known**, so the kinetic fit can be *graded* rather than admired. This is what
   makes `kinetics_peak_rel_error` and CI coverage real metrics instead of adjectives.
3. **Dirt can be injected on purpose.** A demo on clean data proves nothing about a tool
   whose entire value is catching dirt.

### What the generator injects deliberately

This is the design decision that matters. The generator does **not** produce clean data:

| Injected problem | Series affected | Which rule it exercises |
|---|---|---|
| Variable lavage dilution (log-normal, CV 0.6) | nasal wash | mucosal device mismatch |
| Arbitrary units (`au_ml`) | nasal wash, saliva | unit incompatibility |
| A second lab with a 1.3× bias | nasosorption | inter-lab caveat |
| ng/mL vs µg/mL for the same quantity | serum | convertible-unit path |
| LLOQ censoring | nasal wash, saliva | censoring flag, LLOQ/2 imputation |
| Missing visits (5%) | all | missingness flag |
| A sparse 3-timepoint series | serum (lab 2) | unidentifiable-fit refusal |
| Titres snapped to two-fold dilutions | serum HAI | discreteness |
| Responder fraction below 1 | all | responder-rate option |
| Saliva as a *mucosal but not nasal* compartment | saliva | compartment distinction |

Result on the demo dataset: 6 series, **14 non-comparable pairs**, each flagged with a
reason and a remedy. The dirt is the test fixture.

### The model behind it

Subject-level true kinetics, shared across every series measuring the same underlying
response — so the nasosorption and lavage series of one participant describe *the same
biology measured two ways*, which is exactly the situation the engine must handle.

Inversion from interpretable shape to Bateman parameters:

```python
bateman_from_shape(peak_day, half_life, baseline, fold_peak) -> (A, ka, ke)
```

so profiles are written in terms a human can argue about (*"peaks around day 14, half-life
about 60 days, about 60% of participants respond"*) rather than in rate constants nobody
can sanity-check. The inversion is verified to round-trip exactly
(`test_shape_inversion_round_trip`).

Three profiles, all illustrative: `laiv_like`, `iiv_im_like`, `adv_in_like`.

Per-subject variability is log-normal (baseline, fold-rise, peak day, half-life), plus
assay noise, plus the dilution and lab-bias factors above. Normalisation to total IgA is
modelled correctly: the total IgA is diluted by the *same* factor, so the ratio genuinely
cancels it — which is why the engine's `conditional` verdict for "both normalised" is
earned rather than assumed.

### Reproducibility

Seeded throughout. `demo_dataset(n, seed)` is deterministic
(`test_generator_is_reproducible`), and the fit is deterministic for a given seed. The
demo can be re-run live in front of people with identical output.

---

## What the demo does

```bash
$ python -m mvc.cli demo
[1/6] domain model -> JSON Schema       13 schema files
[2/6] evidence base                     10 studies (6 citable), 24 verified findings
[3/6] scenario -> candidate plan        visits [0, 3, 7, 28, 42, 120, 180]
                                        coverage 8/10 evidence-backed · self-check pass
[5/6] synthetic demo dataset            2220 rows, 60 subjects
[4/6] comparability + uncertainty       6 series · 14 non-comparable pairs flagged
[6/6] roadmap                           20 tasks
```

~8 seconds, CPU only, no network, no LLM required. Artefacts in `outputs/`:
`strategy.md`, `strategy_trace.json`, `comparability_matrix.csv`, `data_audit.csv`,
`roadmap.md`, `roadmap.csv`, `figure_*.html`.

## The 90-second demo script

1. **The problem.** Show two nasal IgA series from the same participants, one lavage, one
   nasosorption. The numbers differ by an order of magnitude. *Same biology, different
   device.*
2. **The refusal.** Show the comparability heatmap: 14 red cells, each with a reason and a
   remedy. The dashboard will not put those two on one axis.
3. **The legitimate comparison.** Switch to the fold-rise view — the intranasal arm's
   mucosal response is visible, the injected arm's is not, and the axis is honest.
4. **The uncertainty.** Point at the sparse series: no curve, just points, and the note
   *"only 3 timepoints: kinetic parameters not identifiable"*.
5. **The text side.** `python -m mvc.cli propose "..."` — 10 options, 2 marked
   `ASSUMPTION`, every other one carrying a verbatim quote, and a list of decisions the
   tool refuses to make.
6. **The honesty check.** `python -m mvc.eval.run` — seven metrics, thresholds, including
   fake-quote detection at 100%.

The thing to say out loud: **the deliverable is not the chart, it is the refusal to draw
the wrong chart.**

## Checks

```bash
python -m mvc.cli synth -n 30
pytest tests/test_kinetics_and_synthetic.py -q
```
