"""Download public sources BEFORE the train (needs Internet).

* Europe PMC REST API  — search, abstracts, open-access full text (JATS XML)
  https://europepmc.org/RestfulWebService
* ClinicalTrials.gov API v2 — registered trial designs (arms, outcomes, timepoints)
  https://clinicaltrials.gov/data-api/api

Only the standard library is used (urllib) so this works on a fresh Windows
Python. Everything is cached under data/raw/ so the rest of the pipeline is
fully offline.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

from .store import ROOT

RAW = ROOT / "data" / "raw"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
CTGOV = "https://clinicaltrials.gov/api/v2/studies"
UA = {"User-Agent": "mucosal-vaccine-copilot/0.1 (learning project)"}

DEFAULT_QUERIES = [
    '(intranasal OR "nasal vaccine" OR LAIV) AND ("nasal IgA" OR "mucosal IgA" OR "secretory IgA") AND kinetics',
    '"live attenuated influenza vaccine" AND "nasal" AND IgA AND adults',
    'nasosorption OR "synthetic absorptive matrix" AND antibody',
    '"nasal wash" AND IgA AND normalization',
    'intranasal COVID-19 vaccine AND mucosal IgA AND phase',
]
DEFAULT_PMIDS = ["23087433", "10720541", "28368490", "39012796", "36229342"]
DEFAULT_NCT = ["NCT04110366", "NCT05522335"]


def _get(url: str, binary: bool = False, retries: int = 3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
                return data if binary else data.decode("utf-8", errors="replace")
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(2 * (i + 1))


def epmc_search(query: str, page_size: int = 25, open_access_only: bool = True) -> list[dict]:
    q = f"({query}) AND OPEN_ACCESS:y" if open_access_only else query
    url = f"{EPMC}/search?" + urllib.parse.urlencode(
        {"query": q, "format": "json", "pageSize": page_size, "resultType": "core"})
    return json.loads(_get(url)).get("resultList", {}).get("result", [])


def epmc_by_pmid(pmid: str) -> dict | None:
    url = f"{EPMC}/search?" + urllib.parse.urlencode(
        {"query": f"EXT_ID:{pmid} AND SRC:MED", "format": "json", "resultType": "core"})
    res = json.loads(_get(url)).get("resultList", {}).get("result", [])
    return res[0] if res else None


def epmc_fulltext_xml(pmcid: str) -> str | None:
    try:
        return _get(f"{EPMC}/{pmcid}/fullTextXML")
    except Exception:
        return None


def ctgov_study(nct: str) -> dict:
    return json.loads(_get(f"{CTGOV}/{nct}"))


def ctgov_search(term: str, page_size: int = 20) -> list[dict]:
    url = f"{CTGOV}?" + urllib.parse.urlencode({"query.term": term, "pageSize": page_size})
    return json.loads(_get(url)).get("studies", [])


def download_all(queries=DEFAULT_QUERIES, pmids=DEFAULT_PMIDS, ncts=DEFAULT_NCT,
                 per_query: int = 15, fulltext: bool = True) -> dict:
    """Fetch everything into data/raw/. Returns a manifest."""
    (RAW / "epmc").mkdir(parents=True, exist_ok=True)
    (RAW / "fulltext").mkdir(parents=True, exist_ok=True)
    (RAW / "ctgov").mkdir(parents=True, exist_ok=True)
    manifest = {"records": [], "fulltext": [], "trials": [], "errors": []}
    seen: set[str] = set()

    def keep(rec: dict):
        rid = rec.get("pmid") or rec.get("id")
        if not rid or rid in seen:
            return
        seen.add(rid)
        (RAW / "epmc" / f"{rid}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
        manifest["records"].append(rid)
        pmcid = rec.get("pmcid")
        if fulltext and pmcid and rec.get("isOpenAccess") == "Y":
            xml = epmc_fulltext_xml(pmcid)
            if xml:
                (RAW / "fulltext" / f"{pmcid}.xml").write_text(xml, encoding="utf-8")
                manifest["fulltext"].append(pmcid)

    for pmid in pmids:
        try:
            rec = epmc_by_pmid(pmid)
            if rec:
                keep(rec)
        except Exception as e:
            manifest["errors"].append(f"pmid {pmid}: {e}")
        time.sleep(0.3)
    for q in queries:
        try:
            for rec in epmc_search(q, page_size=per_query):
                keep(rec)
        except Exception as e:
            manifest["errors"].append(f"query {q!r}: {e}")
        time.sleep(0.3)
    for nct in ncts:
        try:
            (RAW / "ctgov" / f"{nct}.json").write_text(json.dumps(ctgov_study(nct), indent=1), encoding="utf-8")
            manifest["trials"].append(nct)
        except Exception as e:
            manifest["errors"].append(f"{nct}: {e}")
    try:
        for st in ctgov_search("intranasal vaccine mucosal IgA", page_size=20):
            nct = st.get("protocolSection", {}).get("identificationModule", {}).get("nctId")
            if nct and nct not in manifest["trials"]:
                (RAW / "ctgov" / f"{nct}.json").write_text(json.dumps(st, indent=1), encoding="utf-8")
                manifest["trials"].append(nct)
    except Exception as e:
        manifest["errors"].append(f"ctgov search: {e}")
    (RAW / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest
