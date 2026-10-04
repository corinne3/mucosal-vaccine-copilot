"""Objective 2 — evidence base, quote verification, retrieval, knowledge graph.

The non-negotiable test in this file is `test_single_word_meaning_flips_are_rejected`:
a verification step that accepts a negated quote would launder fabrications.
"""

from __future__ import annotations

import json

import pytest

from mvc.evidence.extract import (
    extract_rules,
    guess_pathogen,
    normalize,
    quote_in_source,
    sentences,
    verify_quotes,
)
from mvc.evidence.graph import build_graph, coverage_gaps, studies_for_tag
from mvc.evidence.ingest import Document, jats_sections, parse_timeframe
from mvc.evidence.search import BM25, HybridSearcher, expand, stem, tokenize
from mvc.evidence.store import CITABLE, ROOT, chunks, load, merge
from mvc.schema import EvidenceBase, EvidenceLevel, Finding


@pytest.fixture(scope="module")
def eb() -> EvidenceBase:
    return load()


# --- the base itself ------------------------------------------------------- #
def test_every_finding_quote_is_in_its_source_text(eb):
    """The seed base's own integrity: no finding may cite a quote its source
    does not contain. `source_text` is abstract + any verbatim body excerpts we
    hold — a quote matching nothing we hold is not evidence."""
    for s in eb.studies:
        for f in s.findings:
            ok, score = quote_in_source(f.quote, s.source_text)
            assert ok, f"{f.finding_id}: quote absent from {s.study_id} (score {score:.2f})"


def test_placeholder_studies_carry_no_citable_findings(eb):
    for s in eb.studies:
        if s.level is EvidenceLevel.to_verify:
            assert not s.findings, f"{s.study_id} is unverified but exposes findings"


def test_citable_studies_have_identifiers(eb):
    for s in eb.studies:
        if s.level in CITABLE:
            assert s.doi or s.pmid, f"{s.study_id} is citable without DOI or PMID"
            assert s.source_text.strip(), f"{s.study_id} is citable without any source text"


def test_studies_declare_their_gaps(eb):
    assert any(s.not_reported for s in eb.studies)


def test_merge_does_not_overwrite_verified_entries(eb):
    fake = EvidenceBase(studies=[eb.studies[0].model_copy(update={
        "citation": "OVERWRITTEN", "level": EvidenceLevel.llm_extracted})])
    out = merge(eb, fake).by_id()
    assert out[eb.studies[0].study_id].citation != "OVERWRITTEN"


def test_merge_fills_placeholders(eb):
    ph = next(s for s in eb.studies if s.level is EvidenceLevel.to_verify)
    better = ph.model_copy(update={"abstract": "real abstract", "level": EvidenceLevel.verified_abstract})
    out = merge(eb, EvidenceBase(studies=[better])).by_id()
    assert out[ph.study_id].level is EvidenceLevel.verified_abstract


# --- quote verification (anti-hallucination) ------------------------------- #
def test_exact_quote_accepted():
    assert quote_in_source("the cat sat", "well, the cat sat on the mat")[0]


def test_typographic_noise_tolerated():
    src = "mucosal IL-33 release in the first 8 hours post-inoculation"
    assert quote_in_source("mucosal  IL–33 release in the first 8 hours post‐inoculation", src)[0]


@pytest.mark.parametrize("fake", [
    "the conventional parenteral influenza vaccine did induce IgA production in saliva",
    "the conventional parenteral influenza vaccine did not reduce IgA production in saliva",
    "the conventional parenteral influenza vaccine clearly induced IgA production in saliva",
])
def test_single_word_meaning_flips_are_rejected(fake):
    """Dropping 'not' barely changes the characters and inverts the claim."""
    src = ("Although the conventional parenteral influenza vaccine did not induce IgA production "
           "in saliva, vaccinated individuals had higher basal levels.")
    ok, _ = quote_in_source(fake, src)
    assert not ok


def test_absent_quote_rejected():
    ok, score = quote_in_source("a completely unrelated sentence about turbines", "mucosal IgA kinetics")
    assert not ok and score < 0.9


def test_empty_quote_rejected():
    assert quote_in_source("", "anything") == (False, 0.0)


def test_normalize_collapses_whitespace_and_dashes():
    assert normalize("A–B   C\n") == "a-b c"


def test_verify_quotes_splits_kept_and_dropped():
    src = "real sentence here"
    rep = verify_quotes([
        Finding(finding_id="a", statement="s", quote="real sentence here"),
        Finding(finding_id="b", statement="s", quote="invented sentence there"),
    ], src)
    assert [f.finding_id for f in rep.kept] == ["a"]
    assert [f.finding_id for f, _ in rep.dropped] == ["b"]
    assert rep.rate == 0.5


# --- rule-based extraction ------------------------------------------------- #
def test_extract_rules_produces_only_verbatim_findings():
    doc = Document(
        doc_id="d1", title="t", year=2024, citation="Test et al. 2024",
        abstract=("We measured nasal IgA by nasal wash and serum IgG by ELISA. "
                  "Mucosal IgA peaked at day 14 while serum IgG peaked later. "
                  "Correlations between compartments were low."))
    study, rep = extract_rules(doc)
    assert study.findings
    assert rep.rate == 1.0
    for f in study.findings:
        assert f.quote in doc.abstract
        assert f.level is EvidenceLevel.extractive_auto


def test_extract_rules_detects_methods_and_assays():
    doc = Document(doc_id="d2", title="t", year=2024, citation="c",
                   abstract="Nasal IgA was collected by nasosorption and measured by ELISA at day 7.")
    study, _ = extract_rules(doc)
    assert any(m.value == "nasosorption" for m in study.sampling_methods)
    assert any(a.value == "elisa_binding" for a in study.assays)
    assert 7 in study.timepoints_days


@pytest.mark.parametrize("text,expected", [
    ("a study of influenza vaccines", "influenza"),
    ("SARS-CoV-2 mucosal immunity", "SARS-CoV-2"),
    ("RSV bronchiolitis in infants", "RSV"),
    ("something about widgets", "unspecified"),
])
def test_guess_pathogen(text, expected):
    assert guess_pathogen(text) == expected


def test_sentences_ignores_fragments():
    assert sentences("Too short. This one is definitely long enough to be kept as a sentence.") == [
        "This one is definitely long enough to be kept as a sentence."]


# --- timeframe parsing ----------------------------------------------------- #
@pytest.mark.parametrize("text,expected", [
    ("Day 28", [28]),
    ("Days 0, 7 and 28", [0, 7, 28]),
    ("6 months post-vaccination", [180]),
    ("2 weeks after dose 2", [14]),
    ("no timepoint here", []),
])
def test_parse_timeframe(text, expected):
    assert parse_timeframe(text) == expected


def test_jats_sections_survives_garbage():
    assert jats_sections("not xml at all") == {}


def test_jats_sections_extracts_titles():
    xml = ("<article><body><sec><title>Methods</title><p>We used nasal wash.</p></sec>"
           "<sec><title>Results</title><p>IgA rose.</p></sec></body></article>")
    out = jats_sections(xml)
    assert out["Methods"] == "We used nasal wash."
    assert out["Results"] == "IgA rose."


# --- retrieval ------------------------------------------------------------- #
def test_tokenize_drops_stopwords_and_stems():
    toks = tokenize("the kinetics of a nasal IgA response")
    assert "the" not in toks and "of" not in toks
    assert stem("kinetics") in toks and "nasal" in toks


def test_tokenize_can_skip_stemming():
    assert "kinetics" in tokenize("the kinetics of a response", apply_stem=False)


def test_expand_adds_synonyms():
    assert stem("mucosal") in expand([stem("nasal")])


def test_synonym_table_is_stemmed_consistently():
    """An unstemmed key could never match a stemmed token, so it would be dead
    configuration that silently does nothing."""
    from mvc.evidence.search import _SYNONYMS_STEMMED

    for key, values in _SYNONYMS_STEMMED.items():
        assert key == stem(key), f"synonym key {key!r} is not in stemmed form"
        for v in values:
            assert v == stem(v), f"synonym value {v!r} is not in stemmed form"


@pytest.mark.parametrize("a,b", [
    ("trials", "trial"),
    ("compared", "comparisons"),
    ("comparability", "comparable"),
    ("compare", "compared"),
    ("sampling", "samples"),
    ("standardisation", "standardization"),
    ("assays", "assay"),
])
def test_stemmer_conflates_the_same_concept(a, b):
    assert stem(a) == stem(b)


@pytest.mark.parametrize("word", ["nasal", "mucosal", "serum", "iga", "elisa"])
def test_stemmer_leaves_domain_terms_alone(word):
    assert stem(word) == word


@pytest.mark.parametrize("word", [
    "response", "responses", "respond", "comparability", "comparisons", "trials",
    "standardisation", "studies", "immunity", "validation", "sampling", "assays",
    "mucosal", "nasal", "iga", "a", "ab",
])
def test_stemmer_is_idempotent(word):
    """A stemmer whose output depends on how many times it ran breaks every
    match where one side was stemmed twice."""
    once = stem(word)
    assert stem(once) == once


def test_cross_trial_comparability_query_finds_its_evidence(eb):
    """The most central question of this project. Without stemming it scored
    zero: "compared across different trials" matched none of the findings about
    "cross-trial comparisons"."""
    s = HybridSearcher(chunks(eb), use_embeddings=False)
    ids = {h.chunk.chunk_id for h in s.search(
        "why can results not be compared across different trials?", k=5, citable_only=True)}
    assert {"rosenheim2026_f01", "rosenheim2026_f02", "rosenheim2026_f09"} & ids


def test_workshop_report_is_present_and_fully_verified(eb):
    """The field's own consensus report grounds the whole project; every one of
    its body quotes must trace to text we actually hold."""
    s = eb.by_id()["rosenheim2026_workshop"]
    assert s.level is EvidenceLevel.verified_fulltext
    assert s.doi == "10.1016/j.vaccine.2026.128944"
    assert len(s.findings) >= 15
    assert s.full_text_excerpts.strip(), "body quotes need their source text stored"
    for f in s.findings:
        ok, score = quote_in_source(f.quote, s.source_text)
        assert ok, f"{f.finding_id} unverified (score {score:.2f})"


def test_source_text_combines_abstract_and_excerpts():
    from mvc.schema import Study

    s = Study(study_id="x", citation="c", year=2026, pathogen="p",
              abstract="A sentence from the abstract.",
              full_text_excerpts="A passage from the body.")
    assert "abstract" in s.source_text and "body" in s.source_text


def test_bm25_ranks_the_relevant_document_first():
    docs = [tokenize("nasal IgA kinetics peak"), tokenize("quantum computing for molecules")]
    scores = BM25(docs).scores(tokenize("nasal IgA"))
    assert scores[0] > scores[1]


def test_bm25_returns_zero_for_unknown_terms():
    scores = BM25([tokenize("nasal IgA")]).scores(tokenize("zzzz"))
    assert scores.sum() == 0


def test_searcher_runs_without_embeddings(eb):
    s = HybridSearcher(chunks(eb), use_embeddings=False)
    assert "BM25 only" in s.mode
    hits = s.search("compartmentalization of mucosal and systemic antibodies", k=3)
    assert hits and hits[0].score > 0


def test_searcher_respects_citable_only(eb):
    s = HybridSearcher(chunks(eb), use_embeddings=False)
    assert all(h.chunk.citable for h in s.search("influenza", k=10, citable_only=True))


def test_searcher_prefers_findings_over_abstracts(eb):
    """Abstracts are lexically dominant; findings are the citable unit."""
    s = HybridSearcher(chunks(eb), use_embeddings=False)
    hits = s.search("do all participants respond to an intranasal vaccine?", k=3, citable_only=True)
    assert any(h.chunk.kind == "finding" for h in hits)


def test_gating_metrics_do_not_depend_on_untracked_data():
    """A threshold that can fail a build must be computed from files in git.
    `extracted_evidence.json` is gitignored, so gating on it meant three
    machines produced three different numbers for the same commit."""
    from mvc.eval.run import run_all

    rep = run_all(fast=True)
    gating = [m for m in rep.metrics if m.gating]
    assert gating, "no gating metric left"
    for m in gating:
        assert "merged" not in m.name, f"{m.name} gates on the untracked merged corpus"
    for m in rep.metrics:
        if "merged" in m.name:
            assert not m.gating, f"{m.name} must be informational only"


def test_curated_evidence_base_excludes_auto_extracted():
    """The curated base must be loadable on its own, whatever the user has
    downloaded — that is what makes the gate reproducible."""
    from mvc.evidence.store import load

    curated = load(include_extracted=False)
    assert all(s.level is not EvidenceLevel.extractive_auto for s in curated.studies)
    assert len(curated.studies) >= 10


def test_retrieval_gold_set_references_real_findings(eb):
    gold = json.loads((ROOT / "data" / "eval" / "retrieval_gold.json").read_text(encoding="utf-8"))
    known = {f.finding_id for s in eb.studies for f in s.findings}
    for case in gold["cases"]:
        missing = set(case["relevant"]) - known
        assert not missing, f"gold set references unknown findings: {missing}"


# --- knowledge graph ------------------------------------------------------- #
def test_graph_links_studies_to_tags(eb):
    g = build_graph(eb)
    assert g.number_of_nodes() > 20
    assert "thwaites2023_laiv" in studies_for_tag(g, "compartmentalization")


def test_graph_tag_lookup_is_empty_for_unknown_tag(eb):
    assert studies_for_tag(build_graph(eb), "not_a_tag") == []


def test_graph_excludes_unverified_studies_from_citable_lookups(eb):
    g = build_graph(eb)
    unverified = {s.study_id for s in eb.studies if s.level is EvidenceLevel.to_verify}
    for tag in ("compartmentalization", "kinetics", "durability"):
        assert not set(studies_for_tag(g, tag, citable_only=True)) & unverified


def test_coverage_gaps_are_reported(eb):
    gaps = coverage_gaps(build_graph(eb))
    assert gaps and all("no evidence for" in g for g in gaps)
