"""OPTION — expose the evidence base and the engines as MCP tools.

Why it matters for an architect: the same logic serves a Streamlit UI, a CLI and
an MCP client (Claude Desktop, Claude Code). The business rules live in one
place; MCP is just another adapter.

Run:  python -m mvc.mcp_server            # stdio transport

Compatible with the MCP Python SDK v2 (`MCPServer`) and v1 (`FastMCP`).
"""

from __future__ import annotations

import json

import pandas as pd

try:  # SDK v2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # pragma: no cover - SDK v1 fallback
    from mcp.server.fastmcp import FastMCP as _Server

from .comparability import MeasurementContext, comparability_matrix, compare, explain
from .evidence.graph import build_graph, coverage_gaps, studies_for_tag
from .evidence.search import HybridSearcher
from .evidence.store import chunks, load
from .kinetics import fit_kinetics
from .roadmap import build_roadmap
from .roadmap import to_markdown as roadmap_md
from .strategy.agent import run_agent
from .synthetic import demo_dataset

server = _Server(
    name="mucosal-vaccine-copilot",
    instructions=(
        "Tools over a mucosal-vaccine trial-design evidence base and its analysis engines. "
        "All data is public literature or synthetic. Outputs are candidate options for review "
        "by qualified domain experts, never clinical advice."
    ),
)

_EB = None
_SEARCHER = None


def _eb():
    global _EB
    if _EB is None:
        _EB = load()
    return _EB


def _searcher() -> HybridSearcher:
    global _SEARCHER
    if _SEARCHER is None:
        _SEARCHER = HybridSearcher(chunks(_eb()))
    return _SEARCHER


@server.tool(description="Search the verified evidence base. Returns findings with verbatim quotes and citations.")
def search_evidence(query: str, k: int = 5, citable_only: bool = True) -> str:
    hits = _searcher().search(query, k=k, citable_only=citable_only)
    return json.dumps({
        "mode": _searcher().mode,
        "hits": [{"chunk_id": h.chunk.chunk_id, "study_id": h.chunk.study_id,
                  "kind": h.chunk.kind, "text": h.chunk.text, "tags": h.chunk.tags,
                  "score": round(h.score, 5)} for h in hits],
    }, indent=2)


@server.tool(description="List the studies in the evidence base with their verification level.")
def list_studies() -> str:
    return json.dumps([{
        "study_id": s.study_id, "citation": s.citation, "year": s.year, "pathogen": s.pathogen,
        "level": s.level.value, "n_findings": len(s.findings),
        "doi": s.doi, "pmid": s.pmid, "not_reported": s.not_reported,
    } for s in _eb().studies], indent=2)


@server.tool(description="Studies supporting a tag (e.g. compartmentalization, durability, responder_rate), via the knowledge graph.")
def studies_by_tag(tag: str) -> str:
    g = build_graph(_eb())
    return json.dumps({"tag": tag, "studies": studies_for_tag(g, tag)}, indent=2)


@server.tool(description="Platform x sampling-method combinations with no evidence in the base (coverage gaps).")
def evidence_gaps() -> str:
    return json.dumps({"gaps": coverage_gaps(build_graph(_eb()))}, indent=2)


@server.tool(description="Decide whether two measurement contexts are comparable, with the reasons and the remedy. Each context is a JSON object with compartment, method, isotype, assay, unit, normalization, lab.")
def check_comparability(context_a: str, context_b: str) -> str:
    a = MeasurementContext.model_validate(json.loads(context_a))
    b = MeasurementContext.model_validate(json.loads(context_b))
    res = compare(a, b)
    return json.dumps({"verdict": res.label, "explanation": explain(res), **res.as_dict()}, indent=2)


@server.tool(description="Propose candidate sampling days and endpoints for a free-text trial scenario. Returns a markdown briefing with evidence, assumptions and open questions for the domain experts.")
def propose_strategy(scenario_text: str) -> str:
    st = run_agent(scenario_text, _eb())
    return st.report


@server.tool(description="Generate the 90-day validation and IP roadmap derived from a scenario's own gaps.")
def generate_roadmap(scenario_text: str, use_demo_data: bool = True) -> str:
    st = run_agent(scenario_text, _eb())
    df = demo_dataset(n=20) if use_demo_data else None
    return roadmap_md(build_roadmap(st, df))


@server.tool(description="Fit antibody kinetics (Bateman model, bootstrap CIs) to a CSV of measurements with columns subject_id, day, value.")
def fit_kinetic_curve(csv_text: str, n_boot: int = 150) -> str:
    import io

    df = pd.read_csv(io.StringIO(csv_text))
    k = fit_kinetics(df, n_boot=n_boot).kinetic
    return k.model_dump_json(indent=2)


@server.tool(description="Pairwise comparability matrix of all measurement series in a long CSV (needs the context columns).")
def comparability_report(csv_text: str) -> str:
    import io

    df = pd.read_csv(io.StringIO(csv_text))
    mat, details = comparability_matrix(df)
    return json.dumps({
        "matrix": mat.to_dict(),
        "problems": [{"a": a, "b": b, "level": r.label,
                      "flags": [f.code for f in r.flags]}
                     for (a, b), r in details.items() if r.label != "comparable"],
    }, indent=2)


@server.tool(description="Generate the synthetic demo dataset as CSV (clearly labelled synthetic).")
def synthetic_demo(n_per_arm: int = 20, seed: int = 42) -> str:
    return demo_dataset(n=n_per_arm, seed=seed).to_csv(index=False)


@server.resource("evidence://studies", description="The full evidence base as JSON.")
def evidence_resource() -> str:
    return _eb().model_dump_json(indent=2)


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
