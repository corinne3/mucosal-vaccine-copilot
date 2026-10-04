"""Structured extraction from papers -> `Study` records, with anti-hallucination checks.

Two extractors, same output schema:

1. `extract_rules`  — keyword/regex, no LLM, offline, deterministic.
   Findings are *verbatim sentences* (extractive), so they cannot be invented.
2. `extract_llm`    — local LLM with JSON-schema-constrained decoding.
   The model must return a verbatim `quote` for every finding.

Then `verify_quotes` checks every quote really appears in the source text
(fuzzy match tolerant to whitespace/dash/case). Findings whose quote is not
found are DROPPED and reported. This is the same idea as coherence validation
of technical documents: never trust a generated claim that cannot be traced
back to its source.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from .. import llm
from ..schema import (
    AssayType,
    Compartment,
    EvidenceLevel,
    Finding,
    Platform,
    Route,
    SamplingMethod,
    Study,
    Vaccine,
)
from .ingest import Document, parse_timeframe

# --------------------------------------------------------------------------- #
# Vocabulary -> controlled terms
# --------------------------------------------------------------------------- #
METHOD_PATTERNS = {
    SamplingMethod.nasal_wash: r"nasal (?:wash|lavage)|nasal washes",
    SamplingMethod.nasosorption: r"nasosorption|synthetic absorptive matri|\bSAM\b strip|nasal absorption",
    SamplingMethod.nasopharyngeal_swab: r"nasopharyngeal swab",
    SamplingMethod.nasal_swab: r"(?:anterior )?nasal swab|nasal mucosal lining fluid",
    SamplingMethod.saliva: r"saliva|salivary",
    SamplingMethod.serum: r"\bserum\b|\bsera\b|plasma",
    SamplingMethod.pbmc: r"\bPBMC|peripheral blood mononuclear|plasmablast",
}
ASSAY_PATTERNS = {
    AssayType.elisa_binding: r"\bELISA\b|binding antibod",
    AssayType.multiplex_binding: r"\bMSD\b|meso scale|luminex|multiplex",
    AssayType.neutralization: r"neutrali[sz]",
    AssayType.hai: r"\bHAI\b|h(?:a)?emagglutination[- ]inhibition|\bHI titers?",
    AssayType.elispot: r"ELISpot|ELISPOT|antibody[- ]secreting cells|\bASC\b",
    AssayType.flow_cytometry: r"flow cytometr|\bTfh\b|CD8\+|CD4\+",
}
ROUTE_PATTERNS = {
    Route.intranasal: r"intranasal|nasal(?:ly)? (?:administered|spray|vaccine)",
    Route.inhaled: r"inhaled|aerosol",
    Route.intramuscular: r"intramuscular|\bIM\b|parenteral",
}
PLATFORM_PATTERNS = {
    Platform.live_attenuated: r"live[- ]attenuated|\bLAIV\b|cold-adapted|FluMist",
    Platform.adenovirus_vector: r"adenovir|ChAd|\bAd5\b|vectored",
    Platform.mrna: r"\bmRNA\b",
    Platform.inactivated: r"inactivated|\bIIV\b|split[- ]virion",
    Platform.protein_subunit: r"subunit|recombinant protein|adjuvanted protein",
}
FINDING_KEYWORDS = {
    "compartmentalization": r"compartment|separately|distinct.*mucos|correlat\w* .* low",
    "kinetics": r"kinetic|peak|wan(?:e|ing)|durab|decline|half-life|persist",
    "timepoints": r"\bday \d+|\d+ days?|weeks? post|months? post",
    "sampling_method": r"nasal wash|lavage|nasosorption|swab|saliva",
    "responder_rate": r"respond|seroconver|\d+% of participants|positive for",
    "correlate_of_protection": r"correlate of protection|protect",
    "prior_immunity": r"prior infection|pre-?existing|baseline|history of",
    "normalization": r"total IgA|normali[sz]|albumin|urea|dilution",
}


def _find(patterns: dict, text: str) -> list:
    return [k for k, p in patterns.items() if re.search(p, text, re.I)]


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z(])", text) if len(s.strip()) > 30]


# --------------------------------------------------------------------------- #
# Quote verification
# --------------------------------------------------------------------------- #
def normalize(t: str) -> str:
    t = unicodedata.normalize("NFKC", t)
    t = t.replace("–", "-").replace("—", "-").replace("−", "-")
    t = re.sub(r"[®™]", "", t)
    return re.sub(r"\s+", " ", t).strip().lower()


def _words(t: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", t)


def quote_in_source(quote: str, source: str, threshold: float = 0.97) -> tuple[bool, float]:
    """Is `quote` really present in `source`?

    Exact (normalised) substring match is the happy path. The fuzzy fallback
    exists only to absorb typographic noise from PDF extraction (ligatures,
    hyphenation, odd whitespace) — NOT to tolerate different wording.

    This is why two conditions must hold together:
      * high character-level similarity on the best-matching window, and
      * the SAME multiset of content words in that window.

    The second condition is the one that matters. A single-word flip
    ("did not induce" -> "did induce", "lower" -> "higher",
    "mucosal" -> "systemic") barely moves the character ratio but inverts the
    meaning, and a verification step that lets those through is worse than no
    verification at all: it would stamp a fabricated claim as sourced.

    Cost note: a *miss* used to slide a window across the whole source, which
    on a 100 kB full text took seconds — and a bulk run multiplies that by
    hundreds of quotes. The anchor prefilter below makes a miss cheap: rare
    words of the quote locate the few plausible windows, and only those are
    compared. It narrows WHERE we look, never WHAT decides, so the two
    conditions above still rule. If not one anchor word is present, the quote
    is absent; the few quotes whose every anchor is mangled by OCR are
    reported as misses rather than silently accepted.
    """
    q, s = normalize(quote), normalize(source)
    if not q:
        return False, 0.0
    if q in s:
        return True, 1.0

    q_word_list = _words(q)
    q_words = sorted(q_word_list)
    L = len(q)

    # --- anchors: the longest (hence rarest) words of the quote --------------
    anchors = sorted({w for w in q_word_list if len(w) >= 6}, key=len, reverse=True)[:4]
    starts: set[int] = set()
    for a in anchors:
        pos = s.find(a)
        while pos != -1 and len(starts) < 400:
            # the quote may start anywhere from just before to L back of the anchor
            lo = max(0, pos - L)
            for i in range(lo, min(pos + 1, max(len(s) - L, 0) + 1), max(1, L // 8)):
                starts.add(i)
            pos = s.find(a, pos + 1)

    if not starts:
        if anchors:
            return False, 0.0
        # no usable anchor (very short quote): fall back to a bounded scan
        starts = set(range(0, max(1, min(len(s), 20000) - L + 1), max(1, L // 8)))

    best = 0.0
    for i in sorted(starts):
        window = s[i:i + L]
        r = difflib.SequenceMatcher(None, q, window).ratio()
        best = max(best, r)
        if r >= threshold and sorted(_words(window)) == q_words:
            return True, r
    return False, best


@dataclass
class VerificationReport:
    kept: list[Finding] = field(default_factory=list)
    dropped: list[tuple[Finding, float]] = field(default_factory=list)

    @property
    def rate(self) -> float:
        n = len(self.kept) + len(self.dropped)
        return len(self.kept) / n if n else 1.0


def verify_quotes(findings: list[Finding], source: str) -> VerificationReport:
    rep = VerificationReport()
    for f in findings:
        ok, score = quote_in_source(f.quote, source)
        (rep.kept.append(f) if ok else rep.dropped.append((f, score)))
    return rep


# --------------------------------------------------------------------------- #
# Extractor 1 — rules (offline)
# --------------------------------------------------------------------------- #
def _vaccines(text: str, pathogen: str) -> list[Vaccine]:
    routes = _find(ROUTE_PATTERNS, text) or [Route.intramuscular]
    platforms = _find(PLATFORM_PATTERNS, text) or [Platform.other]
    return [Vaccine(name=f"{p.value} ({r.value})", pathogen=pathogen, platform=p, route=r)
            for r in routes[:2] for p in platforms[:1]]


def guess_pathogen(text: str) -> str:
    for name, pat in {"influenza": r"influenza|\bflu\b|H1N1|H3N2", "SARS-CoV-2": r"SARS-CoV-2|COVID",
                      "RSV": r"\bRSV\b|respiratory syncytial", "pertussis": r"pertussis|Bordetella"}.items():
        if re.search(pat, text, re.I):
            return name
    return "unspecified"


def extract_rules(doc: Document, max_findings: int = 6) -> tuple[Study, VerificationReport]:
    text = doc.full_text
    methods = _find(METHOD_PATTERNS, text)
    findings = []
    for i, sent in enumerate(sentences(doc.abstract or text)):
        tags = _find(FINDING_KEYWORDS, sent)
        if not tags or not re.search(r"IgA|IgG|antibod|mucos|nasal|saliva", sent, re.I):
            continue
        findings.append(Finding(finding_id=f"{doc.doc_id}_r{i}", statement=sent, quote=sent,
                                tags=tags, level=EvidenceLevel.extractive_auto))
        if len(findings) >= max_findings:
            break
    rep = verify_quotes(findings, text)
    pathogen = guess_pathogen(text)
    study = Study(
        study_id=f"auto_{doc.doc_id}", citation=doc.citation, year=doc.year or 0, doi=doc.doi,
        pmid=doc.pmid, url=doc.url, pathogen=pathogen, vaccines=_vaccines(text, pathogen),
        sampling_methods=methods,
        compartments=sorted({m_c for m_c in (_method_compartment(m) for m in methods)}, key=lambda c: c.value),
        timepoints_days=[d for d in parse_timeframe(doc.abstract) if 0 <= d <= 730],
        assays=_find(ASSAY_PATTERNS, text), abstract=doc.abstract, findings=rep.kept,
        not_reported=[n for n, v in {"sampling_method": methods, "assay": _find(ASSAY_PATTERNS, text)}.items() if not v],
        level=EvidenceLevel.extractive_auto,
    )
    return study, rep


def _method_compartment(m: SamplingMethod) -> Compartment:
    from ..schema import METHOD_COMPARTMENT

    return METHOD_COMPARTMENT[m]


# --------------------------------------------------------------------------- #
# Extractor 2 — local LLM with constrained JSON
# --------------------------------------------------------------------------- #
class _LLMFinding(BaseModel):
    statement: str = Field(description="one-sentence claim relevant to mucosal vaccine trial design")
    quote: str = Field(description="EXACT verbatim sentence from the text supporting the claim")
    tags: list[str]


class _LLMStudy(BaseModel):
    pathogen: str
    vaccine_platform: str
    vaccine_route: str
    population: str
    n_participants: int | None
    sampling_methods: list[str]
    timepoints_days: list[int]
    assays: list[str]
    findings: list[_LLMFinding]
    not_reported: list[str]


SYSTEM = """You extract trial-design evidence for mucosal (intranasal) vaccine studies.
Rules:
- Use ONLY information present in the text. If something is absent, add it to not_reported.
- Every finding MUST include an exact verbatim quote copied from the text.
- Allowed sampling_methods: nasal_wash, nasal_swab, nasopharyngeal_swab, nasosorption, saliva, serum, pbmc.
- Allowed assays: elisa_binding, multiplex_binding, neutralization, hai, elispot, flow_cytometry.
- Allowed tags: compartmentalization, kinetics, timepoints, sampling_method, responder_rate,
  correlate_of_protection, prior_immunity, normalization, endpoint_choice, durability, early_sampling.
- Convert timepoints to days (1 week = 7, 1 month = 30)."""


def extract_llm(
    doc: Document, max_chars: int = 12000, abstract_only: bool = True
) -> tuple[Study, VerificationReport]:
    """Extract with a local LLM.

    `abstract_only` defaults to True because generation cost scales with the
    prompt: a 3B model on a CPU reads an abstract in well under a minute and a
    12 kB full text in several, which turns a 90-document corpus into hours.
    The abstract carries the trial-design facts this project needs; pass
    abstract_only=False for a deliberate deep pass on a few chosen papers.
    """
    used_abstract = bool(abstract_only and doc.abstract)
    source = doc.abstract if used_abstract else doc.full_text
    text = source[:max_chars]
    data = llm.chat_json(f"TEXT:\n{text}", schema=_LLMStudy.model_json_schema(), system=SYSTEM)
    parsed = _LLMStudy.model_validate(data)
    findings = [Finding(finding_id=f"{doc.doc_id}_l{i}", statement=f.statement, quote=f.quote,
                        tags=f.tags, level=EvidenceLevel.llm_extracted)
                for i, f in enumerate(parsed.findings)]
    # Verify against the text the model was actually shown, plus the abstract:
    # a quote the model could not have read is not evidence.
    rep = verify_quotes(findings, source)

    def _enum(cls, vals):
        out = []
        for v in vals:
            try:
                out.append(cls(v))
            except ValueError:
                pass
        return out

    methods = _enum(SamplingMethod, parsed.sampling_methods)
    try:
        vacc = [Vaccine(name=f"{parsed.vaccine_platform} ({parsed.vaccine_route})", pathogen=parsed.pathogen,
                        platform=Platform(parsed.vaccine_platform), route=Route(parsed.vaccine_route))]
    except ValueError:
        vacc = _vaccines(doc.full_text, parsed.pathogen)
    study = Study(
        study_id=f"llm_{doc.doc_id}", citation=doc.citation, year=doc.year or 0, doi=doc.doi, pmid=doc.pmid,
        url=doc.url, pathogen=parsed.pathogen, vaccines=vacc, population=parsed.population,
        n_participants=parsed.n_participants, sampling_methods=methods,
        compartments=sorted({_method_compartment(m) for m in methods}, key=lambda c: c.value),
        timepoints_days=[d for d in parsed.timepoints_days if 0 <= d <= 730],
        assays=_enum(AssayType, parsed.assays), abstract=doc.abstract, findings=rep.kept,
        not_reported=parsed.not_reported, level=EvidenceLevel.llm_extracted,
    )
    return study, rep


def extract(doc: Document, use_llm: bool | None = None) -> tuple[Study, VerificationReport, str]:
    if use_llm is None:
        use_llm = llm.is_available(llm.LLM_MODEL)
    if use_llm:
        try:
            s, r = extract_llm(doc)
            return s, r, "llm"
        except (llm.LLMUnavailable, ValueError):
            pass
    s, r = extract_rules(doc)
    return s, r, "rules"
