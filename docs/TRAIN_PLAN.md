# Train plan — Saint-Gaudens → Tours

The repo is already complete and tested, so the train is not for *building* it. It is
for **making it yours**: reading each module, running it, breaking it, changing it.
Nobody can defend code in an interview that they have only watched someone else write.

Assume unreliable wifi. Everything below works offline **if** you ran
`python scripts/download_pack.py` at home.

---

## Before leaving the house (30–40 min, needs wifi)

```bash
cd mucosal-vaccine-copilot
python scripts/download_pack.py
```

Then confirm:

```bash
python -m mvc.cli doctor
```

You want to see: every package `OK`, `Ollama reachable: True`, the three models
`present`, `raw/epmc` with 50+ files, `raw/ctgov` non-empty.

If Ollama will not install, go anyway — every feature has a rule-based fallback and the
test suite does not need a model. You will lose the LLM extractor, the LLM scenario
parser, dense retrieval and figure digitisation.

Also download, outside the repo: 2–3 PDFs of the papers you find most interesting, so you
have something real to run the PDF path on.

---

## Hour 1 — make it run, then make it break

```bash
python -m mvc.cli demo          # ~8 s, writes outputs/
python -m pytest -q             # 144 tests, ~40 s
python -m mvc.eval.run          # 7 metrics
python -m mvc.cli dashboard     # open the browser, click every tab
```

Then read `outputs/strategy.md` end to end. That file is what you will show people.

**Now break things deliberately** — this is the fastest way to understand a codebase:

1. In `src/mvc/comparability.py`, comment out the body of `different_compartment`. Re-run
   `pytest -q`. Which tests fail, and does the dashboard now draw nasal and serum on one
   axis? Put it back.
2. In `src/mvc/evidence/extract.py`, lower the `threshold` in `quote_in_source` to 0.92
   and drop the word-multiset condition. Re-run `python -m mvc.eval.run`. Watch
   `extraction_fake_detection` fall below 1.0. That is the bug the eval caught during the
   build — see it with your own eyes, because it is the best story in the project.
3. In `src/mvc/kinetics.py`, set `min_timepoints=2`. Re-run the demo and look at what the
   sparse 3-point series now claims about half-life. Put it back.

---

## Hour 2 — the two modules you must know cold

### `comparability.py` (~200 lines)

Read every rule. For each, ask: *why is this `not_comparable` rather than `conditional`?*
Then do this exercise in a REPL:

```python
from mvc.eval.run import _ctx
from mvc.comparability import compare, explain
print(explain(compare(_ctx(), _ctx(compartment="serum", method="serum"))))
print(explain(compare(_ctx(method="nasal_wash"), _ctx(method="nasosorption"))))
```

**Then add a rule of your own.** A genuine gap: *time-window mismatch* — two series whose
sampling days differ by more than the tolerated window are not comparable at "day 28" even
if everything else matches. Write it, add a labelled pair to `COMPARABILITY_CASES`, make
the eval pass. That rule is yours and you will be able to say so.

### `kinetics.py` (~190 lines)

Understand three things:

1. Why residuals are on log10 (multiplicative noise).
2. Why the bootstrap resamples **subjects**, not rows (repeated measures are correlated).
   Change it to resample rows and watch `kinetics_ci_coverage` behave differently.
3. Why `min_timepoints=4` for a 4-parameter model.

---

## Hour 3 — the evidence pipeline

```bash
python -m mvc.cli search "does nasal IgA correlate with serum IgG"
python -m mvc.cli graph
python -m mvc.cli build-evidence --no-llm     # deterministic extractor on the downloaded corpus
```

Compare `data/evidence/seed_evidence.json` (hand-verified, 6 citable studies) with
`data/evidence/extracted_evidence.json` (auto-extracted). Read ten auto-extracted findings
and judge them yourself. **How many would you actually cite?** That number is the honest
answer to "does your extraction work", and it is a far better interview answer than a
score.

Then, if Ollama came along:

```bash
python -m mvc.cli build-evidence              # LLM extractor
```

Diff the two. Where did the LLM add value, and where did quote verification save you?

**Add a study by hand** to `seed_evidence.json` from one of the PDFs you brought: real
citation, verbatim quotes, honest `not_reported` list. Run
`pytest tests/test_evidence.py -q` — the integrity test will tell you immediately if a
quote is not actually in the abstract you pasted.

---

## Hour 4 — the agent and the design maths

```bash
python -m mvc.cli propose "intranasal RSV vaccine in infants, 4 visits, 90 days" --print
```

Read the trace. Then deliberately give it something contradictory:

```bash
python -m mvc.cli propose "nasal flu vaccine, 2 visits, I want durability and correlates"
```

Watch `critique` fail and `revise` repair exactly once. Follow that path in
`strategy/agent.py` with the code open.

For `optimal_design.py`, the thing to internalise is one sentence: *the Jacobian of the
model with respect to its parameters tells you how much a sample at day t moves the
parameters, and D-optimality picks the day set that maximises the determinant of the
resulting information matrix.* Verify it empirically:

```python
from mvc.strategy.optimal_design import compare_designs
from tests.test_strategy_and_roadmap import scenario   # or build a TrialScenario by hand
print(compare_designs(scenario(max_visits=5),
      {"spread": [0, 7, 14, 28, 180], "clustered": [0, 1, 2, 3, 4]}))
```

The clustered design must score worse. If you can explain *why* in one sentence, you own
this module.

---

## Remaining time — your own extension

Pick one and finish it. A finished small thing beats three half-built ones.

- **Time-window rule** (above) — smallest, highest value.
- **Censored-data handling**: replace LLOQ/2 with a likelihood that treats values below
  LLOQ as "< LLOQ". Compare the estimated baseline before and after.
- **Hierarchical kinetics**: partial pooling across subjects, so sparse series become
  usable instead of only flagged. The most impressive, the most work.
- **Figure digitisation on a real paper**: run `extract_figures_from_pdf` on a PDF you
  brought, then `python -m mvc.cli digitize <png>`. Even a rejection is a good demo — it
  shows the validation layer working.
- **MCP in Claude Desktop**: wire `python -m mvc.cli mcp` into your client config and
  query the evidence base conversationally. Strong live demo, little code.

---

## Arriving at Tours — the first three things

1. **Ask Lovaltech about IP and publication, before writing a line with them.** Whether
   anything from their track can go on your GitHub is their call, and asking first is both
   correct and the mark of someone who has worked in industry. Your repo exists precisely
   so you are not dependent on that answer.
2. **Introduce the repo as an offer, not a decision.** Literally: *"I prepared a working
   prototype on public data for the six objectives. Take any part that is useful, ignore
   the rest, and tell me where the immunology is wrong."* The expert must shape the
   domain content — that is why every option carries an open question.
3. **Find Aymeric S.** (20 years pharma R&D and Class III devices, in the participant
   list) and, once your team has three members, book **Sara** (patent attorney, biotech)
   for objective 6.

---

## Honest check before you present anything

- [ ] Can you explain the comparability verdict for every pair in the heatmap?
- [ ] Can you say why fold-rise is the only cross-compartment scale?
- [ ] Can you tell the quote-verification story (0.92 threshold → single-word flips → word
      multiset → 94% to 100%)?
- [ ] Can you state what the tool **refuses** to do, and why that is the feature?
- [ ] Can you name the three biggest weaknesses without being prompted?

If any answer is no, that module is where the remaining train time goes.
