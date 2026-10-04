"""Knowledge graph of the evidence base (networkx).

Nodes : Study, Vaccine platform, Route, SamplingMethod, Compartment, Assay, Tag, Finding
Edges : study -USES_METHOD-> method, study -MEASURES-> compartment,
        study -TESTS-> platform, platform -GIVEN_BY-> route,
        study -REPORTS-> finding, finding -ABOUT-> tag

Useful questions it answers (see `query_*`):
  * which studies support a given tag (e.g. 'compartmentalization')?
  * which sampling methods were used for intranasal live-attenuated vaccines?
  * what is NOT covered (gaps): e.g. no study with nasosorption + adenovirus vector
"""

from __future__ import annotations

import itertools

import networkx as nx

from ..schema import EvidenceBase
from .store import CITABLE


def build_graph(eb: EvidenceBase) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    for s in eb.studies:
        sid = f"study:{s.study_id}"
        g.add_node(sid, kind="study", label=s.citation.split(".")[0], year=s.year,
                   citable=s.level in CITABLE, level=s.level.value)
        for v in s.vaccines:
            p, r = f"platform:{v.platform.value}", f"route:{v.route.value}"
            g.add_node(p, kind="platform", label=v.platform.value)
            g.add_node(r, kind="route", label=v.route.value)
            g.add_edge(sid, p, rel="TESTS")
            g.add_edge(p, r, rel="GIVEN_BY", study=s.study_id)
        for m in s.sampling_methods:
            n = f"method:{m.value}"
            g.add_node(n, kind="method", label=m.value)
            g.add_edge(sid, n, rel="USES_METHOD")
        for c in s.compartments:
            n = f"compartment:{c.value}"
            g.add_node(n, kind="compartment", label=c.value)
            g.add_edge(sid, n, rel="MEASURES")
        for a in s.assays:
            n = f"assay:{a.value}"
            g.add_node(n, kind="assay", label=a.value)
            g.add_edge(sid, n, rel="USES_ASSAY")
        for f in s.findings:
            fn = f"finding:{f.finding_id}"
            g.add_node(fn, kind="finding", label=f.statement, quote=f.quote)
            g.add_edge(sid, fn, rel="REPORTS")
            for t in f.tags:
                tn = f"tag:{t}"
                g.add_node(tn, kind="tag", label=t)
                g.add_edge(fn, tn, rel="ABOUT")
    return g


def studies_for_tag(g: nx.MultiDiGraph, tag: str, citable_only: bool = True) -> list[str]:
    tn = f"tag:{tag}"
    if tn not in g:
        return []
    out = set()
    for fn in g.predecessors(tn):
        for sid in g.predecessors(fn):
            if not citable_only or g.nodes[sid].get("citable"):
                out.add(sid.split(":", 1)[1])
    return sorted(out)


def methods_for(g: nx.MultiDiGraph, platform: str, route: str) -> dict[str, list[str]]:
    res: dict[str, list[str]] = {}
    for sid, data in g.nodes(data=True):
        if data.get("kind") != "study":
            continue
        succ = set(g.successors(sid))
        p, r, study = f"platform:{platform}", f"route:{route}", sid.split(":", 1)[1]
        same_vaccine = g.has_edge(p, r) and any(
            e.get("study") == study for e in g.get_edge_data(p, r).values()
        )
        if p in succ and same_vaccine:
            for n in succ:
                if n.startswith("method:"):
                    res.setdefault(n.split(":", 1)[1], []).append(sid.split(":", 1)[1])
    return res


def coverage_gaps(g: nx.MultiDiGraph) -> list[str]:
    """Combinations platform x method that no study covers — where evidence is missing."""
    platforms = [n for n, d in g.nodes(data=True) if d.get("kind") == "platform"]
    methods = [n for n, d in g.nodes(data=True) if d.get("kind") == "method"]
    gaps = []
    for p, m in itertools.product(platforms, methods):
        studies_p = {s for s in g.predecessors(p)}
        studies_m = {s for s in g.predecessors(m)}
        if not studies_p & studies_m:
            gaps.append(f"no evidence for {p.split(':')[1]} + {m.split(':')[1]}")
    return gaps


def to_plot_data(g: nx.MultiDiGraph, seed: int = 3) -> dict:
    """Positions + edges for a plotly figure (no extra dependency)."""
    simple = nx.Graph(g)
    pos = nx.spring_layout(simple, seed=seed, k=0.6)
    nodes = [{"id": n, "x": float(pos[n][0]), "y": float(pos[n][1]), **{k: v for k, v in d.items()
             if isinstance(v, (str, int, float, bool))}} for n, d in g.nodes(data=True)]
    edges = [{"source": u, "target": v} for u, v in simple.edges()]
    return {"nodes": nodes, "edges": edges}
