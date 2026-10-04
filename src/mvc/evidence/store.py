"""Load / merge / save the evidence base and turn it into searchable chunks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..schema import EvidenceBase, EvidenceLevel, Study

ROOT = Path(__file__).resolve().parents[3]
SEED_PATH = ROOT / "data" / "evidence" / "seed_evidence.json"
EXTRACTED_PATH = ROOT / "data" / "evidence" / "extracted_evidence.json"

#: evidence levels that may be cited as support in a recommendation
CITABLE = {
    EvidenceLevel.verified_abstract, EvidenceLevel.verified_fulltext,
    EvidenceLevel.llm_extracted, EvidenceLevel.extractive_auto,
}


def load(path: Path | str = SEED_PATH, include_extracted: bool = True) -> EvidenceBase:
    eb = EvidenceBase.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
    if include_extracted and EXTRACTED_PATH.exists() and Path(path) == SEED_PATH:
        extra = EvidenceBase.model_validate(json.loads(EXTRACTED_PATH.read_text(encoding="utf-8")))
        eb = merge(eb, extra)
    return eb


def merge(base: EvidenceBase, extra: EvidenceBase) -> EvidenceBase:
    """`extra` wins over `to_verify` placeholders, never over verified entries."""
    studies = base.by_id()
    for s in extra.studies:
        cur = studies.get(s.study_id)
        if cur is None or cur.level == EvidenceLevel.to_verify:
            studies[s.study_id] = s
    return EvidenceBase(version=base.version, description=base.description, studies=list(studies.values()))


def save(eb: EvidenceBase, path: Path | str) -> None:
    Path(path).write_text(eb.model_dump_json(indent=2), encoding="utf-8")


@dataclass
class Chunk:
    chunk_id: str
    study_id: str
    kind: str          # finding | abstract
    text: str
    tags: list[str]
    citable: bool


def chunks(eb: EvidenceBase) -> list[Chunk]:
    out: list[Chunk] = []
    for s in eb.studies:
        citable = s.level in CITABLE
        for f in s.findings:
            out.append(Chunk(
                f.finding_id, s.study_id, "finding",
                f"{f.statement} Quote: \"{f.quote}\" ({s.citation})",
                f.tags, citable and f.level in CITABLE,
            ))
        if s.abstract:
            out.append(Chunk(f"{s.study_id}_abstract", s.study_id, "abstract",
                             f"{s.citation}\n{s.abstract}", [], citable))
    return out


def citable_findings(eb: EvidenceBase, tags: set[str]) -> list[tuple[Study, object]]:
    """All citable findings carrying at least one of `tags`."""
    res = []
    for s in eb.studies:
        if s.level not in CITABLE:
            continue
        for f in s.findings:
            if f.level in CITABLE and tags & set(f.tags):
                res.append((s, f))
    return res
