# Domain primer — enough immunology to hold the conversation

Written for a software/AI architect walking into a mucosal-vaccine track. The point is
**not** to make you an immunologist. It is to let you ask the right questions, understand
why the engineering choices are what they are, and recognise when you are out of your
depth — which, on this subject, is most of the time and is fine, because the team has an
immunologist and a clinical trial expert for exactly that.

Statements below marked **[E]** are backed by a verified quote in the project's evidence
base (`data/evidence/seed_evidence.json`); you can check each one with
`python -m mvc.cli search "..."`. Statements marked **[G]** are general background of the
kind found in textbooks and reviews; treat them as orientation, not as citable claims.

---

## 1. Why nasal vaccines are interesting at all

An injected vaccine is very good at putting antibodies in your blood. But a respiratory
virus arrives at the lining of your nose and throat, replicates there, and is transmitted
from there. An intranasal vaccine aims to put defences where the virus actually lands —
with the hope of blocking infection and transmission rather than only preventing severe
disease. **[E]** *"Intranasal vaccination may induce protective local and systemic immune
responses against respiratory pathogens."* (Madhavan 2022)

That is the promise. The measurement problem is the catch.

---

## 2. The two compartments, and the word "compartmentalised"

- **Systemic compartment** — blood. The antibody that matters there is mostly **IgG**.
  Easy to sample (a tube of blood), well-standardised assays, decades of regulatory
  precedent.
- **Mucosal compartment** — the lining of the nose and airways. The antibody that matters
  there is mostly **secretory IgA (sIgA)**: a dimer carrying a "secretory component" that
  lets it survive being secreted onto a wet surface. **[G]**

The critical fact for this project: these two are **not two views of one thing**.

**[E]** *"LAIV induces distinct, compartmentalized, antibody responses in the mucosa and
blood."* (Thwaites 2023)

**[E]** *"Correlations between mucosal IgA and serum IgG against specific antigens were
low, whether before or after challenge, suggesting a compartmentalization of immune
responses."* (Bean 2024)

**What this means in engineering terms:** serum is not a proxy for mucosa. If you design
a nasal vaccine trial with serum-only endpoints, you may measure a weak response and
conclude the vaccine failed, when what failed was your instrumentation. This is why the
tool refuses to put nasal and serum values on the same absolute axis, and why it proposes
carrying a mucosal endpoint alongside the systemic ones.

Note also: **saliva is mucosal but it is not nasal.** Different site, different
secretions. The schema treats `oral` and `nasal` as distinct compartments for that reason.
Several studies in the base use saliva as the mucosal readout **[E]** (Singh 2023;
Sheikh-Mohamed 2022; Tsunetsugu-Yokota 2022) — convenient, but it answers a slightly
different question than a nasal sample.

---

## 3. How you sample a nose, and why the device changes the number

This is the single most important technical detail of the whole track.

| Device | What it does | Dilution |
|---|---|---|
| **Nasal wash / lavage** | squirt saline in, collect what comes out | large and **variable** — you do not know how much mucosal fluid is in your sample |
| **Nasal swab** | wipe the inside of the nostril | moderate, variable recovery |
| **Nasosorption** (synthetic absorptive matrix strip) | rest an absorbent strip against the lining, let it soak up undiluted lining fluid | minimal — this is the point of the method |
| **Nasopharyngeal swab** | deeper, behind the nose | moderate; less comfortable |

A lavage sample might be mucosal fluid diluted 10- or 50-fold by saline, and the factor
differs between visits and between participants. So **a raw lavage IgA value and a raw
nasosorption IgA value are not on the same scale**, and neither is a lavage value from
Monday compared to one from Friday.

**The fix: normalisation.** Divide the antigen-specific IgA by the **total IgA** in the
same sample. Both are diluted by the same unknown factor, so the ratio cancels it. Other
denominators used for the same purpose: total protein, albumin, urea. **[G]**

This is why `Normalization` is an enum in the schema and not a footnote, why the
comparability engine treats "different devices with no shared normalisation" as
`not_comparable` but "different devices, both normalised to total IgA" as `conditional`,
and why the synthetic generator deliberately injects a variable dilution factor on the
lavage series.

**Nasosorption's other advantage:** it is minimally invasive, which matters when you need
many visits, and more so in children.

---

## 4. Kinetics: the shape of a response over time

What a kinetic curve looks like **[G]**: a baseline, a delay, a rise, a peak, then a
decay. Four numbers describe it usefully — baseline, amplitude, time to peak, half-life
— which is exactly the Bateman parameterisation the project fits.

What the evidence base says about timing:

**[E]** *"We detected an early (6–10 days post-infection) increase of sIgA in five of the
seven samples and a later (3–5 weeks) increase of sIgG in six of the seven saliva
samples."* (Tsunetsugu-Yokota 2022)

→ Mucosal IgA moves **early**; IgG appears in mucosal fluid **later**. So an early visit
and a later visit measure different things, and a single timepoint cannot characterise
both.

**[E]** *"At 6 months post-dose 2, these participants exhibited diminished anti-Spike/RBD
IgG levels, although secretory component-associated anti-Spike Ab were more stable."*
(Sheikh-Mohamed 2022)

→ Durability differs by antibody type, and you only see it with a **late** visit. This is
the evidence behind the tool's rule that asking about durability forces a late sample —
and behind the kinetics module refusing to report a half-life it cannot constrain.

**[E]** *"we find associations with mucosal IL-33 release in the first 8 hours
post-inoculation and divergent CD8+ and circulating T follicular helper (cTfh) T cell
responses 7 days post-inoculation."* (Thwaites 2023)

→ Very early events (hours) carry signal too. Worth knowing when someone proposes a
first visit at day 7.

**[E]** *"On Day 42, 14 days after the second dose, BBV154 induced significant serum
neutralization antibody titers"* (Singh 2023)

→ A real phase 3 read-out two weeks after the second dose. This is the kind of reported
timepoint the tool uses as an anchor, instead of inventing a schedule.

---

## 5. Not everyone responds — plan for it

**[E]** *"This formulation of intranasal ChAdOx1 nCoV-19 showed an acceptable tolerability
profile but induced neither a consistent mucosal antibody response nor a strong systemic
response."* (Madhavan 2022)

**[E]** *"Administration of a second dose of mRNA boosted the IgG but not the IgA
response, with only 30% of participants remaining positive for IgA at this timepoint."*
(Sheikh-Mohamed 2022)

Two consequences for anyone building the analysis:

1. **A mean hides this.** Average a group where 40% responded strongly and 60% not at all,
   and you get a modest-looking response that describes nobody. Report the **responder
   fraction** per timepoint alongside the central tendency.
2. **Sample size depends on the responder rate**, which is a biostatistician's problem.
   The tool raises it and refuses to answer it.

---

## 6. Prior immunity ruins clean comparisons

**[E]** *"vaccinated individuals with a history of influenza infection had higher basal
levels of sIgA than those without a history."* (Tsunetsugu-Yokota 2022)

**[E]** *"extensive evaluation of T cell immunity revealed comparable responses in both
cohorts due to prior infection."* (Singh 2023)

**[E]** *"volunteers who developed viral shedding for multiple days had lower baseline
titers across both systemic and mucosal compartments"* (Bean 2024)

Nobody in 2026 is immunologically naive to influenza or SARS-CoV-2. Prior exposure raises
baselines and can **mask differences between arms** entirely. Hence: a day-0 sample in
every compartment is non-negotiable, and stratification on prior immunity is a question
for the experts.

---

## 7. Assays and units — where false precision comes from

| Assay | Measures | Typical unit |
|---|---|---|
| **ELISA (binding)** | how much antibody sticks to the antigen | AU/mL, ng/mL, BAU/mL, OD |
| **Multiplex (MSD, Luminex)** | same, many antigens at once | AU/mL |
| **Neutralisation** | whether antibody actually blocks the virus | titre (reciprocal dilution) |
| **HAI** | influenza-specific functional assay | titre |
| **ELISpot** | counts antibody-secreting cells | spots per million cells |

Two traps:

- **Binding ≠ functional.** A lot of antibody that binds but does not neutralise is not
  the same result as a little that does. The engine treats different assay types as
  `not_comparable`.
- **"AU/mL" means nothing across labs.** Arbitrary units are defined by that laboratory's
  standard curve. **[E]** *"We established a quantitative ELISA to measure the amount of
  influenza virus-specific salivery IgA (sIgA) and salivary IgG (sIgG) antibodies using a
  standard antibody broadly reactive to the influenza A virus."* (Tsunetsugu-Yokota 2022)
  — that is what makes values quantitative rather than arbitrary. Without a shared
  reference standard, compare fold-rises, not levels.

**Titres are discrete.** They come from two-fold serial dilutions, so they take values
10, 20, 40, 80… A "1.3-fold rise" in a titre is not a measurement, it is an artefact.
The synthetic generator snaps titre series to the dilution ladder for this reason.

**LLOQ** (lower limit of quantification): below it, the assay cannot measure, only say
"less than". The common shortcut is to impute LLOQ/2, which biases means downward. The
project does this in the demo data *and* raises replacing it as a roadmap task, which is
the honest handling of a known shortcut.

---

## 8. Correlate of protection — the thing nobody has

A "correlate of protection" is a measurable immune marker above which you are protected.
For injected influenza vaccines, serum HAI titre has served as one for decades. **[G]**

For **nasal** vaccines, there isn't one:

**[E]** *"a correlate of protection for LAIV remains unclear."* (Thwaites 2023)

**[E]** *"Mucosal antibodies ... may provide a correlate of protection for mucosal
vaccination."* (Thwaites 2023) — note "may".

**[E]** *"multivariate models were unable to account for the variability in outcomes,
emphasizing our imperfect understanding of immune correlates in influenza."* (Bean 2024)

**How to use this in the room:** if anyone — including a pitch deck — claims the project
establishes a correlate of protection, that is a claim well beyond what the data supports.
The tool is built to say so: `correlate_of_protection` as a scenario question adds an
exploratory endpoint and an explicit open question stating that no accepted correlate
exists in this evidence base.

---

## 9. A useful comparison to keep in your head

Two routes, same pathogen:

| | Intranasal live-attenuated | Injected inactivated |
|---|---|---|
| Mucosal IgA | the intended effect **[E]** | little or none **[E]** (Tsunetsugu-Yokota 2022: *"did not induce IgA production in saliva"*) |
| Serum response | often weaker **[E]** (Madhavan 2022) | strong **[E]** (Bean 2024: *"predominantly boosting serum antibody titers"*) |

This is the demo scenario, and it is the clearest illustration of the project's thesis:
**judge each vaccine in the compartment it is designed to act on**, and if you must
compare across compartments, compare shape, not level.

---

## 10. Questions to ask the immunologist on day one

Ordered by how much the answers change the build:

1. Which nasal sampling device will we assume, and what is its recovery efficiency?
2. Do we normalise specific IgA to total IgA, and is that the accepted practice for this
   assay?
3. Which antigen, and do we need secretory-component detection to call it sIgA?
4. Is there a reference standard available, or are we in arbitrary units?
5. What counts as a responder, at which timepoint?
6. What is the realistic responder rate — which drives sample size?
7. How will prior immunity be measured and handled?
8. Binding, neutralisation, or both — and can one lab do all of it?
9. Which timepoints are clinically feasible, as opposed to statistically desirable?
10. What claim are we allowed to make at the end, and which are off the table?

Questions 1–4 and 8 directly determine what the comparability engine will flag. Question
10 determines what the pitch may say.

---

## Sources

The verified studies behind the **[E]** statements, with their identifiers:

- Thwaites RS, Uruchurtu ASS, Negri VA, et al. *Early mucosal events promote distinct mucosal and systemic antibody responses to live attenuated influenza vaccine.* Nature Communications, 2023. [doi:10.1038/s41467-023-43842-7](https://doi.org/10.1038/s41467-023-43842-7) · NCT04110366
- Bean R, Giurgea LT, Han A, et al. *Mucosal correlates of protection after influenza viral challenge of vaccinated and unvaccinated healthy volunteers.* mBio, 2024. [doi:10.1128/mbio.02372-23](https://doi.org/10.1128/mbio.02372-23)
- Madhavan M, Ritchie AJ, Aboagye J, et al. *Tolerability and immunogenicity of an intranasally-administered adenovirus-vectored COVID-19 vaccine: an open-label partially-randomised ascending dose phase I trial.* EBioMedicine, 2022. [doi:10.1016/j.ebiom.2022.104298](https://doi.org/10.1016/j.ebiom.2022.104298) · PMID 36229342
- Singh C, Verma S, Reddy P, et al. *Phase III pivotal comparative clinical trial of intranasal (iNCOVACC) and intramuscular COVID-19 vaccine (Covaxin).* npj Vaccines, 2023. [doi:10.1038/s41541-023-00717-8](https://doi.org/10.1038/s41541-023-00717-8) · NCT05522335
- Sheikh-Mohamed S, Isho B, Chao GYC, et al. *Systemic and mucosal IgA responses are variably induced in response to SARS-CoV-2 mRNA vaccination and are associated with protection against subsequent infection.* Mucosal Immunology, 2022. [doi:10.1038/s41385-022-00511-0](https://doi.org/10.1038/s41385-022-00511-0)
- Tsunetsugu-Yokota Y, Ito S, Adachi Y, et al. *Saliva as a useful tool for evaluating upper mucosal antibody response to influenza.* PLOS ONE, 2022. [doi:10.1371/journal.pone.0263419](https://doi.org/10.1371/journal.pone.0263419)

Four further studies sit in the evidence base as `to_verify` placeholders (Barría 2013
PMID 23087433; Belshe 2000 PMID 10720541; Thwaites 2017 PMID 28368490; M2SR 2024
PMID 39012796). Their abstracts could not be retrieved when the base was built, so they
are **not citable** — run `python -m mvc.cli download` with network to complete them.
