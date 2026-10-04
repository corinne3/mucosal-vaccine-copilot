"""Objective 4 — Streamlit dashboard.

    streamlit run app/dashboard.py

Tabs map to the objectives:
  Scenario       -> 3: free text -> candidate plan, with the agent's trace
  Kinetics       -> 4: curves with bootstrap bands, one panel per comparable group
  Comparability  -> 4: pairwise matrix + per-flag explanations
  Uncertainty    -> 4: data-quality audit
  Evidence       -> 2: search, studies, knowledge graph, coverage gaps
  Roadmap        -> 6: generated 90-day plan
  Quality        -> options: eval suite
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from mvc import llm  # noqa: E402
from mvc.comparability import (  # noqa: E402
    audit_table,
    comparability_matrix,
    explain,
    harmonize_units,
)
from mvc.consortia import (  # noqa: E402
    cross_consortium_summary,
    load_table1,
    metadata_gap_report,
    shared_methods,
)
from mvc.evidence.graph import build_graph, coverage_gaps, to_plot_data  # noqa: E402
from mvc.evidence.search import HybridSearcher  # noqa: E402
from mvc.evidence.store import chunks, load  # noqa: E402
from mvc.figures import (  # noqa: E402
    comparability_heatmap,
    design_figure,
    fold_rise_figure,
    graph_figure,
    kinetics_figure,
    uncertainty_figure,
)
from mvc.kinetics import fit_kinetics  # noqa: E402
from mvc.roadmap import build_roadmap, to_dataframe, to_markdown  # noqa: E402
from mvc.strategy.agent import compare_parsers, run_agent  # noqa: E402
from mvc.synthetic import demo_dataset  # noqa: E402

st.set_page_config(page_title="Mucosal Vaccine Copilot", page_icon="🧪", layout="wide")


# --------------------------------------------------------------------------- #
# Streamlit API shim
#
# `use_container_width` is how Streamlit stretched a chart or table to its
# column; newer versions take `width="stretch"` and drop the old keyword.
# Rather than rewrite eleven call sites (and risk getting it wrong on the
# version the user actually has), the two functions are wrapped once here and
# the old keyword is translated only if this install no longer accepts it.
# Call sites stay untouched, so there is nothing to keep in sync.
# --------------------------------------------------------------------------- #
def _accepts(fn, name: str) -> bool:
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):  # C-implemented or wrapped callables
        return False


def _shim_container_width(fn):
    def wrapper(*args, use_container_width=None, **kw):
        if use_container_width is not None:
            kw["width"] = "stretch" if use_container_width else "content"
        return fn(*args, **kw)

    return wrapper


for _name in ("plotly_chart", "dataframe"):
    _fn = getattr(st, _name)
    if not _accepts(_fn, "use_container_width") and _accepts(_fn, "width"):
        setattr(st, _name, _shim_container_width(_fn))


@st.cache_data(show_spinner=False)
def _evidence():
    return load()


@st.cache_resource(show_spinner=False)
def _searcher(embeddings_available: bool):
    """The searcher, rebuilt if the embedding model's availability changes.

    `cache_resource` keeps one instance for the whole server process. A
    searcher built during the seconds when Ollama was still starting had
    already fallen back to BM25, and that fallback then outlived the reason
    for it: the sidebar reported the model as pulled while the search mode
    underneath said "no embedding model", in the same breath. Making
    availability part of the cache key means the degraded instance is
    replaced as soon as the model answers, instead of being frozen in.
    """
    return HybridSearcher(chunks(load()), use_embeddings=embeddings_available)


@st.cache_resource(show_spinner=False)
def _table1():
    # cache_resource, not cache_data: Table1 holds pydantic models, which
    # cache_data would try to hash and copy on every rerun.
    return load_table1()


@st.cache_data(show_spinner=False)
def _data(n: int, seed: int) -> pd.DataFrame:
    return demo_dataset(n=n, seed=seed)


@st.cache_data(show_spinner=False)
def _agent(text: str):
    st_ = run_agent(text, load())
    # the report travels with the rest: rebuilding it for the download button
    # meant a second full agent run on every rerender of the page
    return st_.proposal, st_.critique, st_.log, st_.parser, st_.retrieved, st_.report


eb = _evidence()

# --------------------------------------------------------------------------- #
st.title("Mucosal Vaccine Copilot")
st.caption(
    "Engineering prototype on **public literature and synthetic data**. Produces candidate "
    "measurement options for review by qualified domain experts — not clinical advice, "
    "not a trial protocol."
)

with st.sidebar:
    st.header("Data")
    source = st.radio("Dataset", ["Synthetic demo", "Upload CSV"], index=0)
    n = st.slider("Participants per arm", 10, 80, 30, step=5, disabled=source != "Synthetic demo")
    seed = st.number_input("Seed", value=42, step=1, disabled=source != "Synthetic demo")
    uploaded = st.file_uploader("Long-format CSV", type="csv") if source == "Upload CSV" else None
    st.divider()
    st.header("Analysis")
    n_boot = st.select_slider("Bootstrap resamples", [50, 100, 150, 300], value=150)
    log_y = st.checkbox("Log y axis", value=True)
    harmonize = st.checkbox("Auto-convert compatible units", value=True)
    st.divider()
    st.header("Local models")
    # "reachable" only means the Ollama service answered. Which models are
    # actually pulled is a different question, and the one that decides what
    # this app can do — so it is the one shown.
    _embeddings_ready = llm.is_available(llm.EMBED_MODEL)
    if llm.is_available():
        st.caption("Ollama service: running")
        for role, model in (("text (scenario parsing, extraction)", llm.LLM_MODEL),
                            ("embeddings (search)", llm.EMBED_MODEL),
                            ("vision (figure reading)", llm.VLM_MODEL)):
            here = llm.is_available(model)
            st.caption(f"{'✅' if here else '○'} {role} — `{model}`"
                       + ("" if here else "  _not pulled, rule-based fallback in use_"))
    else:
        st.caption("Ollama service: not running — every feature falls back to rules")
    mode = _searcher(_embeddings_ready).mode
    st.caption(f"**Search mode:** {mode}")
    if _embeddings_ready and "BM25 only" in mode:
        st.caption("_The model is pulled but the corpus is not embedded yet — "
                   "run a search once to build the cache (a minute on CPU)._")

if uploaded is not None:
    df = pd.read_csv(uploaded)
else:
    df = _data(n, int(seed))
if harmonize:
    df = harmonize_units(df)

required = {"subject_id", "day", "value", "compartment", "method", "isotype", "assay", "unit"}
missing = required - set(df.columns)
if missing:
    st.error(f"Missing columns: {sorted(missing)}")
    st.stop()
for col, default in [("normalization", "none"), ("antigen", "unspecified"), ("lab", "lab_1"),
                     ("source", "measured"), ("below_lloq", False), ("arm_id", "A")]:
    if col not in df.columns:
        df[col] = default

# Two independent tools share this screen, and nothing on it said so — which
# is exactly the confusion the first user hit. Each tab now declares its input.
READS_LITERATURE = (
    "📚 **Reads the published literature.** Nothing here depends on the "
    "measurement table or on the sidebar's data controls."
)
READS_MEASUREMENTS = (
    "📊 **Reads the measurement table** (sidebar: Dataset, Participants, Seed). "
    "Nothing here depends on the literature."
)
READS_BOTH = "🔗 **Uses both**: the literature for the options, the measurement table for the data gaps."

READS_TABLE1 = (
    "🏥 **Reads Table 1 of the workshop report** — six real consortia and how they "
    "sample. The only non-synthetic measurement data in the project. Nothing here "
    "depends on the sidebar."
)

tabs = st.tabs(["Scenario", "Kinetics", "Comparability", "Uncertainty", "Evidence",
                "Consortia (Table 1)", "Roadmap", "Quality"])

# --------------------------------------------------------------------------- 1
with tabs[0]:
    st.info(READS_LITERATURE)
    st.subheader("Describe a trial scenario in plain words")
    text = st.text_area(
        "Scenario", height=110,
        value=("Phase 1 comparison of an intranasal live-attenuated influenza vaccine against the "
               "injected inactivated vaccine in 40 healthy adults, 7 visits maximum over 180 days. "
               "We care about the peak, durability and the mucosal versus systemic comparison."))
    st.caption("The participant count written here describes the trial being designed. It is "
               "deliberately unrelated to the sidebar's 'Participants per arm', which sizes the "
               "simulated measurement table used by the other tabs.")
    with st.expander("🧪 Rules vs local LLM — run both parsers on this sentence"):
        st.caption(
            "This box accepts free text, but free text does **not** imply a language "
            "model. By default the sentence is read by a keyword parser — about 60 "
            "lines of `if` statements. Press the button to run the local LLM on the "
            "same sentence and see, field by field, whether it reads it differently. "
            "“We have an LLM” and “the LLM helps” are different claims; only the "
            "second is worth making, and this is how you check it."
        )
        if st.button("Compare the two parsers"):
            with st.spinner("Parsing twice…"):
                cmp = compare_parsers(text)
            if not cmp["llm_ran"]:
                st.warning(
                    f"Only the rules ran — {cmp['error']}. "
                    f"To enable the model: `ollama pull {cmp['model']}`, then press again."
                )
                st.dataframe(pd.DataFrame({"field": list(cmp["rules"]),
                                           "rules": list(cmp["rules"].values())}),
                             use_container_width=True, hide_index=True)
            else:
                diff = set(cmp["differences"])
                st.dataframe(
                    pd.DataFrame({
                        "field": list(cmp["rules"]),
                        "keyword rules": list(cmp["rules"].values()),
                        f"local LLM ({cmp['model']})": [cmp["llm"][k] for k in cmp["rules"]],
                        "agree": ["—" if k in diff else "✅" for k in cmp["rules"]],
                    }),
                    use_container_width=True, hide_index=True)
                if diff:
                    st.warning(
                        f"**{len(diff)} field(s) differ:** {', '.join(sorted(diff))}. "
                        "A difference is not a verdict — neither parser is ground truth "
                        "here. Read the sentence and decide which one got it right."
                    )
                else:
                    st.success(
                        "Both parsers agree on every field. On plain phrasing that is "
                        "the expected result, and it is the argument for keeping the "
                        "rules on the critical path: same answer, no model, no wait."
                    )

    if st.button("Propose a candidate plan", type="primary"):
        with st.spinner("Running the agent…"):
            proposal, critique, log, parser, retrieved, report = _agent(text)
        cov = proposal.coverage
        c = st.columns(4)
        c[0].metric("Visits", len(proposal.sampling_days))
        c[1].metric("Options", cov["options"])
        c[2].metric("Evidence-backed", f"{cov['evidence_backed']}/{cov['options']}")
        c[3].metric("Self-check", "pass" if critique.passed else "FAIL")
        st.plotly_chart(design_figure(proposal.candidate_days, proposal.sampling_days,
                                      [0] + [d for d in proposal.sampling_days if d <= 28]),
                        use_container_width=True)
        st.info("**Proposed visits:** " + ", ".join(f"D{d}" for d in proposal.sampling_days))
        for note in proposal.design_notes:
            st.caption(note)

        st.markdown("#### Candidate options")
        for o in proposal.options:
            icon = "⚠️" if o.assumption else "✅"
            with st.expander(f"{icon} {o.option_id} · {o.choice}", expanded=o.assumption):
                st.write(o.rationale)
                if o.assumption:
                    st.warning("No supporting evidence in the base — this is an unverified assumption.")
                for e in o.evidence:
                    st.markdown(f"**{e.citation}**")
                    st.markdown(f"> {e.quote}")
                    if e.url:
                        st.caption(e.url)
                if o.expert_review:
                    st.markdown(f"**For the expert:** {o.expert_review}")
        if proposal.open_questions:
            st.markdown("#### Expert decisions required (out of scope here)")
            for q in proposal.open_questions:
                st.markdown(f"- {q}")
        with st.expander("Agent trace and self-check"):
            st.code("\n".join(f"{i+1}. {m}" for i, m in enumerate(log)))
            st.json(critique.checks)
            if critique.issues:
                st.error("\n".join(critique.issues))
        st.download_button("Download briefing (Markdown)", data=report,
                           file_name="strategy.md")

# --------------------------------------------------------------------------- 2
with tabs[1]:
    st.info(READS_MEASUREMENTS)
    st.subheader("Mucosal vs systemic kinetics")
    st.caption("Series the comparability engine marks *not comparable* are never drawn on the "
               "same absolute axis — they get their own panel. The fold-rise view below is the "
               "only shared scale.")
    st.plotly_chart(kinetics_figure(df, n_boot=n_boot, log_y=log_y), use_container_width=True)
    st.plotly_chart(fold_rise_figure(df), use_container_width=True)
    st.markdown("#### Fitted parameters")
    rows = []
    for (arm, comp, meth, unit), g in df.groupby(["arm_id", "compartment", "method", "unit"]):
        k = fit_kinetics(g, n_boot=n_boot).kinetic
        rows.append({
            "arm": arm, "compartment": comp, "method": meth, "unit": unit,
            "peak day": round(k.peak_day, 1) if k.peak_day == k.peak_day else None,
            "peak day 95% CI": f"{k.ci_peak_day[0]:.0f}–{k.ci_peak_day[1]:.0f}" if k.ci_peak_day else "—",
            "half-life (d)": round(k.half_life_days, 0) if k.half_life_days else None,
            "fold-rise": round(k.fold_rise, 2) if k.fold_rise else None,
            "identifiable": k.identifiable, "notes": "; ".join(k.notes) or "—",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# --------------------------------------------------------------------------- 3
with tabs[2]:
    st.info(READS_MEASUREMENTS)
    st.subheader("Which measurements may be compared?")
    mat, details = comparability_matrix(df)
    bad = [(a, b, r) for (a, b), r in details.items() if r.label == "not_comparable"]
    cond = [(a, b, r) for (a, b), r in details.items() if r.label == "conditional"]
    c = st.columns(3)
    c[0].metric("Series", len(mat))
    c[1].metric("Not comparable", len(bad))
    c[2].metric("Conditional", len(cond))
    st.plotly_chart(comparability_heatmap(mat), use_container_width=True)
    st.markdown("#### Why")
    for label, pairs in [("Not comparable", bad), ("Conditional", cond)]:
        for a, b, r in pairs:
            with st.expander(f"[{label}] {a[:48]}  ×  {b[:48]}"):
                st.code(explain(r))

# --------------------------------------------------------------------------- 4
with tabs[3]:
    st.info(READS_MEASUREMENTS)
    st.subheader("Data quality and uncertainty")
    st.plotly_chart(uncertainty_figure(df), use_container_width=True)
    audit = audit_table(df)
    st.dataframe(audit.assign(flags=audit["flags"].apply(lambda f: "; ".join(f) or "—")),
                 use_container_width=True, hide_index=True)
    st.caption("Values below the limit of quantification are imputed at LLOQ/2 in the demo data; "
               "the roadmap raises replacing that with a proper censored-data method.")

# --------------------------------------------------------------------------- 5
with tabs[4]:
    st.info(READS_LITERATURE)
    st.subheader("Evidence base")
    q = st.text_input("Search", "does nasal IgA correlate with serum IgG?")
    citable_only = st.checkbox("Citable sources only", value=True)
    if q:
        for h in _searcher(_embeddings_ready).search(q, k=6, citable_only=citable_only):
            st.markdown(f"**`{h.chunk.chunk_id}`** · score {h.score:.4f} · ranks {h.ranks}")
            st.markdown(f"> {h.chunk.text}")
            st.caption(" · ".join(h.chunk.tags) or "no tag")
            st.divider()
    st.markdown("#### Studies")
    st.dataframe(pd.DataFrame([{
        "id": s.study_id, "year": s.year, "pathogen": s.pathogen, "level": s.level.value,
        "findings": len(s.findings), "doi": s.doi or s.pmid or "", "citation": s.citation,
    } for s in eb.studies]), use_container_width=True, hide_index=True)
    st.markdown("#### Knowledge graph")
    g = build_graph(eb)
    st.plotly_chart(graph_figure(to_plot_data(g)), use_container_width=True)
    with st.expander(f"Coverage gaps ({len(coverage_gaps(g))})"):
        for gap in coverage_gaps(g):
            st.markdown(f"- {gap}")

# --------------------------------------------------------------------------- 6
with tabs[5]:
    st.info(READS_TABLE1)
    st.subheader("Can six real consortia compare their numbers?")
    st.caption("Table 1 of the workshop report lists how six ongoing trials sample the "
               "airway and which assays they run. Each consortium is expanded into one "
               "measurement context per (sampling method × assay × isotype), and every "
               "pair is put through the same rule engine as the synthetic data. The "
               "engine sees metadata only — these trials have published no values.")
    t1 = _table1()
    summary = cross_consortium_summary(t1)
    n_pairs = len(summary)
    n_cond = int((summary["verdict"] == "conditional").sum())

    c1, c2, c3 = st.columns(3)
    c1.metric("Measurement contexts", len(t1.series), help="from 6 consortia")
    c2.metric("Cross-consortium pairs", n_pairs)
    c3.metric("Not ruled out", n_cond, help="every one of them conditional; none is 'comparable'")

    st.markdown("#### Where the field has already converged")
    st.caption("The optimistic half, and it is worth saying first.")
    st.dataframe(shared_methods(t1), use_container_width=True, hide_index=True)

    st.markdown("#### What Table 1 does not record")
    st.caption("The engine needs ten fields to reach a verdict. Table 1 records five of "
               "them. These are the other five, and what each one decides.")
    st.dataframe(metadata_gap_report(t1), use_container_width=True, hide_index=True)

    st.markdown(f"#### The {n_cond} pairs the missing metadata actually decides")
    st.caption("For every other pair, something Table 1 *does* record already rules the "
               "comparison out — a different compartment, device, isotype or assay. For "
               "these, everything recorded agrees, so whether the two numbers may be "
               "compared depends entirely on the five fields above. These are the pairs "
               "a reporting standard would change.")
    st.dataframe(
        summary[summary["decided_by_unrecorded_metadata"]][
            ["series_a", "series_b", "verdict"]],
        use_container_width=True, hide_index=True)

    with st.expander(f"Table 1 cells this project does not model ({len(t1.unmodelled)})"):
        st.caption("Recorded rather than dropped, so the loss is visible.")
        for u in t1.unmodelled:
            st.markdown(f"- **{u.consortium}** · *{u.kind}* · “{u.verbatim}” — {u.reason}")

    st.info(
        "**Read this as a measurement of the table, not of the science.** A published "
        "methods table, as currently written, does not carry enough metadata for a "
        "reader to know whether two trials' antibody numbers can be compared. That is a "
        "checkable claim, and it names the five columns a harmonised reporting standard "
        "would have to add. It says nothing about the quality of any trial."
    )

# --------------------------------------------------------------------------- 7
with tabs[6]:
    st.info(READS_BOTH)
    st.subheader("90-day validation & IP roadmap")
    st.caption("Generated from this run's own gaps: unsupported options, failed self-checks, "
               "thin series, non-comparable pairs.")
    scenario = st.text_input("Scenario", "intranasal LAIV vs injected IIV in 40 adults, 7 visits, durability")
    if st.button("Generate roadmap"):
        with st.spinner("Building…"):
            state = run_agent(scenario, eb)
            rm = build_roadmap(state, df)
        st.dataframe(to_dataframe(rm), use_container_width=True, hide_index=True)
        st.download_button("Download roadmap (Markdown)", data=to_markdown(rm), file_name="roadmap.md")
        st.markdown("#### IP — facts")
        for f in rm.ip_facts:
            st.markdown(f"- {f}")
        st.markdown("#### IP — questions for counsel")
        for qq in rm.ip_questions:
            st.markdown(f"- {qq}")

# --------------------------------------------------------------------------- 8
with tabs[7]:
    st.subheader("Does this thing work? (eval suite)")
    st.caption("Retrieval against a hand-judged gold set, hallucination detection on corrupted "
               "quotes, kinetic parameter recovery against known truth, comparability rules on "
               "labelled pairs.")
    if st.button("Run evals"):
        from mvc.eval.run import run_all

        with st.spinner("Running…"):
            rep = run_all(fast=True)
        st.dataframe(pd.DataFrame([{
            "metric": m.name, "value": round(m.value, 3), "threshold": m.threshold,
            "status": "PASS" if m.passed else "FAIL", "detail": m.detail,
        } for m in rep.metrics]), use_container_width=True, hide_index=True)
        (st.success if rep.passed else st.error)("OVERALL: " + ("PASS" if rep.passed else "FAIL"))
