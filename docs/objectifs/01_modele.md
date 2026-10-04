# Objective 1 — Structured model

> *"a structured model covering trial design, nasal sampling, immune endpoints and kinetics"*

**Module:** `src/mvc/schema.py` · **Tests:** `tests/test_schema.py` (23) ·
**Export:** `python -m mvc.cli schema` → 13 JSON Schema files in `schemas/`

---

## The design principle

Every measured value carries its full **measurement context**. Not as metadata on the
side — as a required field without which the object cannot exist.

```python
class MeasurementContext(_Base):
    compartment:   Compartment       # nasal | oral | serum | blood_cells
    method:        SamplingMethod    # nasosorption | nasal_wash | swab | saliva | serum | pbmc
    isotype:       Isotype           # IgA | sIgA | IgG | IgM | total | na
    assay:         AssayType         # elisa_binding | neutralization | hai | elispot | ...
    unit:          Unit              # titer | ng_ml | ug_ml | au_ml | bau_ml | ratio | ...
    normalization: Normalization     # none | total_iga | total_protein | albumin | urea
    antigen:       str
    lab:           str
    lloq:          float | None
    source:        str               # measured | digitized_from_figure | synthetic
```

A bare number — `47.3` — cannot be compared with anything. `47.3 AU/mL of antigen-specific
IgA, nasal lavage, un-normalised, ELISA, lab 1` can. The comparability engine
(objective 4) is only possible because this context exists, and the whole project rests on
that.

## The four blocks the brief asks for

| Block | Types |
|---|---|
| Trial design | `Vaccine`, `Arm`, `Population`, `TrialDesign` |
| Nasal sampling | `SamplingMethod`, `SamplingEvent`, `METHOD_COMPARTMENT` |
| Immune endpoints | `ImmuneEndpoint` (compartment × method × isotype × assay × unit × normalisation) |
| Kinetics | `KineticParameters`, `Measurement`, `MeasurementContext` |

Plus the input and output types of objective 3 (`TrialScenario`) and objective 2
(`Study`, `Finding`, `EvidenceBase`, `EvidenceLevel`).

## Validators — the model refuses incoherent designs

This is where a schema earns its place. Four classes of error are made unrepresentable:

**1. A sampling device cannot measure a compartment it does not touch.**

```python
ImmuneEndpoint(compartment=Compartment.nasal, method=SamplingMethod.serum, ...)
# ValidationError: sampling method serum does not sample compartment nasal
```

`METHOD_COMPARTMENT` is the single source of truth, and `SamplingEvent.compartment`
derives from the method rather than being supplied — so the two can never disagree.

**2. An endpoint with no matching sampling event.**

```python
TrialDesign(endpoints=[serum_igg], sampling=[nasal_visit_only], ...)
# ValidationError: endpoints without matching sampling events: ['serum_igg']
```

A protocol declaring an endpoint it never collects a sample for is a silent, expensive
bug. Here it cannot be instantiated.

**3. Sampling after the end of follow-up**, and **4. unsorted dose days** — same idea,
cheaply caught.

`extra="forbid"` is set on every model, so a typo in a field name is an error rather than
a silently ignored value.

## Controlled vocabularies, and the distinctions that matter

Free-text fields would defeat the whole purpose: `"nasal wash"`, `"nasal lavage"` and
`"NW"` must be one thing. Three enum distinctions carry real meaning:

- **`nasal` vs `oral`** — saliva is mucosal but it is *not* nasal. Different site,
  different secretions, different question. Several studies in the evidence base use
  saliva as their mucosal readout, which is convenient and not equivalent.
- **`IgA` vs `sIgA`** — secretory IgA is a subset of IgA, identified by detecting the
  secretory component. The engine treats this pair as `conditional`, not interchangeable.
- **`Normalization`** — a first-class field, because it is the mechanism that rescues
  comparability between mucosal sampling devices (see objective 4).

`UNIT_CONVERSIONS` holds only genuinely fixed factors (ng/mL ↔ µg/mL). `au_ml` appears in
no conversion pair, deliberately: arbitrary units are defined by one lab's standard curve
and converting them would be fiction.

## EvidenceLevel — a lattice, not a flag

```python
verified_abstract  verified_fulltext  llm_extracted  extractive_auto   # citable
expert_assumption  to_verify                                           # NOT citable
```

Only the first group may be cited in a recommendation (`evidence/store.py::CITABLE`).
`to_verify` entries stay in the base so the gaps are *visible* — the roadmap generates a
task for each — but the knowledge graph excludes them from citable lookups and the
resolver refuses them.

## Why pydantic

- Validators run at construction, so an invalid state never propagates.
- `model_json_schema()` gives a language-neutral contract for free — useful if a team-mate
  wants to build a frontend or another service against the same model.
- `model_copy(update=...)` makes the agent's revision step safe: scenarios are never
  mutated in place.

## Trade-offs taken knowingly

- **Enums over free text.** Less flexible, and a sampling device nobody anticipated needs a
  code change. Accepted: in exchange, two spellings of the same thing can never be
  compared as if they were different, or vice versa.
- **No regulatory, safety, consent or scheduling fields.** Out of scope on purpose —
  modelling them badly would invite the tool to be mistaken for a protocol generator.
- **`lloq` on the context, not on the assay.** The limit of quantification is in practice a
  property of a run, not of a method.
- **Flat `Measurement` rows rather than nested structures.** Pandas-friendly, which keeps
  the analysis code simple; the cost is that context is repeated on every row.

## Checks

```bash
python -m mvc.cli schema     # export the contracts
pytest tests/test_schema.py -q
```

The test file is worth reading as documentation: each test names one incoherent design the
model must reject.
