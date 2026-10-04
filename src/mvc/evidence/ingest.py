"""Turn raw downloads (Europe PMC JSON, JATS XML, PDF, ClinicalTrials.gov JSON) into clean text."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .fetch import RAW


@dataclass
class Document:
    doc_id: str
    title: str
    year: int | None
    citation: str
    abstract: str
    sections: dict[str, str] = field(default_factory=dict)  # name -> text
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    url: str | None = None

    @property
    def full_text(self) -> str:
        return "\n\n".join([self.abstract] + [f"{k}\n{v}" for k, v in self.sections.items()])


def _clean(t: str) -> str:
    t = re.sub(r"<[^>]+>", " ", t or "")
    return re.sub(r"\s+", " ", t).strip()


def from_epmc_record(rec: dict) -> Document:
    authors = rec.get("authorString", "")
    first = authors.split(",")[0] if authors else "Anon"
    year = int(rec["pubYear"]) if rec.get("pubYear", "").isdigit() else None
    journal = rec.get("journalInfo", {}).get("journal", {}).get("title", "")
    title = _clean(rec.get("title", ""))
    return Document(
        doc_id=rec.get("pmid") or rec.get("id"),
        title=title,
        year=year,
        citation=f"{first} et al. {title} {journal}. {year}.",
        abstract=_clean(rec.get("abstractText", "")),
        doi=rec.get("doi"), pmid=rec.get("pmid"), pmcid=rec.get("pmcid"),
        url=f"https://europepmc.org/article/MED/{rec.get('pmid')}" if rec.get("pmid") else None,
    )


def jats_sections(xml: str) -> dict[str, str]:
    """Extract top-level <sec> titles and their paragraph text from JATS XML."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return {}
    body = root.find(".//body")
    if body is None:
        return {}
    out: dict[str, str] = {}
    for sec in body.findall("./sec"):
        title_el = sec.find("title")
        name = _clean("".join(title_el.itertext())) if title_el is not None else "section"
        paras = [_clean("".join(p.itertext())) for p in sec.iter("p")]
        out[name or "section"] = " ".join(p for p in paras if p)
    return out


def pdf_text(path: str | Path) -> dict[str, str]:
    """PDF -> {page_n: text} with PyMuPDF (optional dependency)."""
    import fitz  # PyMuPDF

    with fitz.open(path) as doc:
        return {f"page_{i + 1}": page.get_text() for i, page in enumerate(doc)}


def load_raw_documents(raw: Path = RAW) -> list[Document]:
    docs = []
    for f in sorted((raw / "epmc").glob("*.json")):
        d = from_epmc_record(json.loads(f.read_text(encoding="utf-8")))
        if d.pmcid and (raw / "fulltext" / f"{d.pmcid}.xml").exists():
            d.sections = jats_sections((raw / "fulltext" / f"{d.pmcid}.xml").read_text(encoding="utf-8"))
        docs.append(d)
    for f in sorted((raw / "pdf").glob("*.pdf")) if (raw / "pdf").exists() else []:
        pages = pdf_text(f)
        docs.append(Document(doc_id=f.stem, title=f.stem, year=None, citation=f.stem,
                             abstract=next(iter(pages.values()), "")[:3000], sections=pages))
    return docs


# --------------------------------------------------------------------------- #
# ClinicalTrials.gov — registered designs give real sampling schedules
# --------------------------------------------------------------------------- #
_TIME = re.compile(
    r"(?:day|d)\s*(-?\d+)|(\d+)\s*days?|(\d+)\s*weeks?|(\d+)\s*months?|week\s*(\d+)|month\s*(\d+)",
    re.I,
)


def parse_timeframe(text: str) -> list[int]:
    """'Day 0, 7, 28 and 6 months' -> [0, 7, 28, 180] (approximate month = 30 d)."""
    days: set[int] = set()
    for m in _TIME.finditer(text or ""):
        d, nd, nw, nm, w2, m2 = m.groups()
        if d is not None:
            days.add(int(d))
        elif nd:
            days.add(int(nd))
        elif nw or w2:
            days.add(7 * int(nw or w2))
        elif nm or m2:
            days.add(30 * int(nm or m2))
    # "Day 0, 7, 28" -> numbers following a 'day' keyword
    for m in re.finditer(r"days?\s*((?:-?\d+\s*(?:,|and|&|to)\s*)+-?\d+)", text or "", re.I):
        days |= {int(x) for x in re.findall(r"-?\d+", m.group(1))}
    return sorted(days)


def summarize_ctgov(study: dict) -> dict:
    ps = study.get("protocolSection", {})
    ident = ps.get("identificationModule", {})
    arms = ps.get("armsInterventionsModule", {}).get("armGroups", [])
    outcomes = ps.get("outcomesModule", {})
    out_list = []
    for kind in ("primaryOutcomes", "secondaryOutcomes"):
        for o in outcomes.get(kind, []):
            out_list.append({
                "kind": kind.replace("Outcomes", ""),
                "measure": o.get("measure", ""),
                "time_frame": o.get("timeFrame", ""),
                "days": parse_timeframe(o.get("timeFrame", "")),
            })
    return {
        "nct": ident.get("nctId"),
        "title": ident.get("briefTitle"),
        "phase": ps.get("designModule", {}).get("phases", []),
        "enrollment": ps.get("designModule", {}).get("enrollmentInfo", {}).get("count"),
        "arms": [{"label": a.get("label"), "type": a.get("type"),
                  "interventions": a.get("interventionNames", [])} for a in arms],
        "outcomes": out_list,
        "all_days": sorted({d for o in out_list for d in o["days"]}),
    }


def load_ctgov(raw: Path = RAW) -> list[dict]:
    return [summarize_ctgov(json.loads(f.read_text(encoding="utf-8")))
            for f in sorted((raw / "ctgov").glob("*.json"))] if (raw / "ctgov").exists() else []
