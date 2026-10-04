# Limits — what this tool must not be used for

One page. Written deliberately, kept short so it is actually read.

## What this is

An engineering prototype that helps a team **reason transparently** about measurement
choices in mucosal vaccine studies. Its output is a set of *candidate options*, each
labelled with the evidence that supports it or marked as an unsupported assumption, plus
an explicit list of decisions it refuses to make.

## What this is not

- **Not clinical advice.** No statement here is a recommendation about a medical
  intervention, for anyone.
- **Not a trial protocol.** A `TrialDesign` object is a data structure, not a document
  anyone may act on. No regulatory, ethical, safety or consent content is modelled at all.
- **Not a medical device**, and not built under any quality system (no ISO 13485, no
  IEC 62304, no GxP).
- **Not a systematic review.** The evidence base is a seed of six citable studies. It is
  not representative and was not assembled by a reproducible search strategy.
- **Not a source of biological estimates.** Every number produced by the synthetic
  generator is fabricated for testing. The parameter values reproduce qualitative patterns
  only and describe no real vaccine.
- **Not a correlate-of-protection engine.** No accepted correlate exists for mucosal
  influenza vaccines in this evidence base, and the tool says so rather than implying one.

## Hard rules

1. **Never present an option as a recommendation.** The word "candidate" and the
   `ASSUMPTION` label exist for this reason and must not be stripped when results are
   copied into slides or documents.
2. **Never mix synthetic and real data** in one view. The comparability engine enforces
   this; do not override it.
3. **Never cite a `to_verify` study.** Those placeholders exist to make gaps visible, not
   to be used.
4. **Never quote a finding without the quote.** If the verbatim text cannot be shown, the
   claim does not get made.
5. **Domain judgement belongs to domain experts.** Endpoint ranking, sample size, device
   acceptability, assay validation, regulatory strategy, IP strategy: the tool raises them
   and stops.
6. **No patient data, no partner data, no confidential material** enters this repository.
   Public literature and synthetic data only.

## Known shortcuts shipped on purpose

| Shortcut | Why it is wrong | Where it is tracked |
|---|---|---|
| Values below LLOQ imputed at LLOQ/2 | biases means downward | roadmap task, generated automatically |
| Month approximated as 30 days in timeframe parsing | drifts on long follow-up | `docs/ARCHITECTURE.md` §7 |
| Kinetic prior for the D-optimal design is an assumption | chosen days are only as good as it | printed next to every schedule |
| Greedy rather than exhaustive design search | can be beaten on small budgets | `docs/ARCHITECTURE.md` §7 |
| Retrieval gold set has 12 queries | small sample, wide confidence interval | roadmap task |

## Author's competence boundary

Written by a software and AI architect, not an immunologist, a clinician or a
biostatistician. The immunology in `docs/DOMAIN_PRIMER.md` is a working summary with its
claims traced to quotes, assembled to ask better questions — not to answer them. Where the
tool appears confident, that confidence is about **data provenance and comparability**,
never about biology.
