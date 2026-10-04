"""Command-line interface — every objective runnable in one command.

    python -m mvc.cli demo                     # objectives 1-6 end to end -> outputs/
    python -m mvc.cli schema                   # objective 1: export JSON Schema
    python -m mvc.cli download                 # objective 2: fetch public sources (needs Internet)
    python -m mvc.cli build-evidence           # objective 2: raw -> extracted evidence
    python -m mvc.cli search "nasal IgA peak"  # objective 2: query the evidence base
    python -m mvc.cli graph                    # objective 2: knowledge-graph stats and gaps
    python -m mvc.cli propose "..."            # objective 3: scenario -> candidate plan
    python -m mvc.cli synth                    # objective 5: write the synthetic dataset
    python -m mvc.cli dashboard                # objective 4: launch Streamlit
    python -m mvc.cli roadmap "..."            # objective 6: roadmap
    python -m mvc.cli eval                     # options: run the eval suite
    python -m mvc.cli digitize fig.png         # options: read a figure with a vision model
    python -m mvc.cli mcp                      # options: start the MCP server
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import llm
from .schema import ALL_MODELS

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs"

DEMO_SCENARIO = (
    "Phase 1 comparison of an intranasal live-attenuated influenza vaccine against the "
    "injected inactivated vaccine in 40 healthy adults, 7 visits maximum over 180 days. "
    "We care about the peak, durability, and the mucosal versus systemic comparison."
)


def _eb():
    from .evidence.store import load

    return load()


def cmd_schema(args) -> None:
    out = ROOT / "schemas"
    out.mkdir(exist_ok=True)
    for model in ALL_MODELS:
        (out / f"{model.__name__}.schema.json").write_text(
            json.dumps(model.model_json_schema(), indent=2), encoding="utf-8")
    print(f"wrote {len(ALL_MODELS)} JSON Schema files to {out}")


def cmd_download(args) -> None:
    from .evidence.fetch import download_all

    m = download_all(per_query=args.per_query, fulltext=not args.no_fulltext)
    print(f"records {len(m['records'])} · full texts {len(m['fulltext'])} · trials {len(m['trials'])}")
    for e in m["errors"][:10]:
        print("  error:", e)


def cmd_build_evidence(args) -> None:
    from .evidence.extract import extract
    from .evidence.ingest import load_ctgov, load_raw_documents
    from .evidence.store import EXTRACTED_PATH, save
    from .schema import EvidenceBase

    import time

    docs = load_raw_documents()
    if not docs:
        print("no raw documents — run `python -m mvc.cli download` first (needs Internet).")
        return
    if args.limit:
        docs = docs[: args.limit]

    use_llm = False if args.no_llm else llm.is_available(llm.LLM_MODEL)
    if use_llm:
        # A 3B model on a CPU takes tens of seconds per abstract. Say so before
        # spending an hour, instead of looking frozen.
        est = len(docs) * 40 / 60
        print(f"LLM extractor: {llm.LLM_MODEL} on {len(docs)} documents, roughly {est:.0f} min on CPU.")
        print("  --no-llm uses the deterministic extractor instead (seconds).")
        print("  --limit N tries a few documents first.")
        if not args.yes and est > 10:
            if input("  continue? [y/N] ").strip().lower() not in ("y", "yes"):
                print("aborted — nothing written.")
                return
    else:
        print(f"deterministic extractor (verbatim sentences) on {len(docs)} documents.")

    studies, kept, dropped, modes = [], 0, 0, {}
    t0 = time.time()
    for i, d in enumerate(docs, start=1):
        study, rep, mode = extract(d, use_llm=use_llm)
        modes[mode] = modes.get(mode, 0) + 1
        kept += len(rep.kept)
        dropped += len(rep.dropped)
        if study.findings:
            studies.append(study)
        elapsed = time.time() - t0
        eta = elapsed / i * (len(docs) - i)
        print(f"  [{i}/{len(docs)}] {d.doc_id} · {mode} · "
              f"{len(rep.kept)} kept / {len(rep.dropped)} dropped · "
              f"{elapsed:.0f}s elapsed, ~{eta:.0f}s left", flush=True)
    eb = EvidenceBase(version="1", description="Auto-extracted, quote-verified. Review before citing.",
                      studies=studies)
    save(eb, EXTRACTED_PATH)
    trials = load_ctgov()
    (ROOT / "data" / "evidence" / "ctgov_designs.json").write_text(json.dumps(trials, indent=2), encoding="utf-8")
    print(f"{len(studies)} studies · findings kept {kept}, dropped by quote check {dropped} "
          f"({kept / max(kept + dropped, 1):.0%} verified) · extractors {modes}")
    print(f"{len(trials)} registered trial designs -> data/evidence/ctgov_designs.json")


def cmd_search(args) -> None:
    from .evidence.search import HybridSearcher
    from .evidence.store import chunks

    s = HybridSearcher(chunks(_eb()))
    print(f"mode: {s.mode}\n")
    for h in s.search(args.query, k=args.k, citable_only=not args.all):
        print(f"[{h.score:.4f}] {h.chunk.chunk_id} ({h.chunk.study_id}) ranks={h.ranks}")
        print(f"    {h.chunk.text[:400]}\n")


def cmd_graph(args) -> None:
    from .evidence.graph import build_graph, coverage_gaps, studies_for_tag

    g = build_graph(_eb())
    print(f"nodes {g.number_of_nodes()} · edges {g.number_of_edges()}")
    tags = sorted(n.split(":", 1)[1] for n, d in g.nodes(data=True) if d.get("kind") == "tag")
    for t in tags:
        print(f"  {t}: {studies_for_tag(g, t)}")
    gaps = coverage_gaps(g)
    print(f"\n{len(gaps)} coverage gaps; first 10:")
    for gap in gaps[:10]:
        print("  -", gap)


def cmd_propose(args) -> None:
    from .strategy.agent import run_agent, trace_json

    st = run_agent(args.scenario, _eb())
    OUT.mkdir(exist_ok=True)
    (OUT / "strategy.md").write_text(st.report, encoding="utf-8")
    (OUT / "strategy_trace.json").write_text(trace_json(st), encoding="utf-8")
    print(st.report if args.print else
          f"visits {st.proposal.sampling_days} · coverage {st.proposal.coverage} · "
          f"self-check {'pass' if st.critique.passed else 'FAIL'}\n-> outputs/strategy.md")


def cmd_synth(args) -> None:
    from .synthetic import save_demo

    p = ROOT / "data" / "synthetic" / "demo_kinetics.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    save_demo(str(p), n=args.n, seed=args.seed)
    print(f"wrote {p}")


def cmd_roadmap(args) -> None:
    from .roadmap import build_roadmap, to_dataframe, to_markdown
    from .strategy.agent import run_agent
    from .synthetic import demo_dataset

    st = run_agent(args.scenario, _eb())
    rm = build_roadmap(st, demo_dataset(n=20))
    OUT.mkdir(exist_ok=True)
    (OUT / "roadmap.md").write_text(to_markdown(rm), encoding="utf-8")
    to_dataframe(rm).to_csv(OUT / "roadmap.csv", index=False)
    print(f"{len(rm.tasks)} tasks -> outputs/roadmap.md, outputs/roadmap.csv")


def cmd_dashboard(args) -> None:
    app = ROOT / "app" / "dashboard.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app)], check=False)


def cmd_eval(args) -> None:
    from .eval.run import run_all

    print(run_all(verbose=True))


def cmd_digitize(args) -> None:
    from .figure_digitizer import digitize, report

    d = digitize(args.image, hint=args.hint)
    print(report(d))
    if d.ok:
        OUT.mkdir(exist_ok=True)
        out = OUT / f"digitized_{Path(args.image).stem}.csv"
        d.rows.to_csv(out, index=False)
        print(f"-> {out}")


def cmd_mcp(args) -> None:
    from .mcp_server import main

    main()


def cmd_doctor(args) -> None:
    """Check the local environment before the train."""
    import importlib

    print("Python", sys.version.split()[0])
    for mod in ["pydantic", "pandas", "numpy", "scipy", "networkx", "plotly", "streamlit", "fitz", "pytest"]:
        try:
            importlib.import_module(mod)
            print(f"  OK      {mod}")
        except ImportError:
            print(f"  MISSING {mod}")
    print(f"Ollama reachable: {llm.is_available()}")
    for m in (llm.LLM_MODEL, llm.EMBED_MODEL, llm.VLM_MODEL):
        print(f"  model {m}: {'present' if llm.is_available(m) else 'absent'}")
    raw = ROOT / "data" / "raw"
    for sub in ("epmc", "fulltext", "ctgov"):
        n = len(list((raw / sub).glob("*"))) if (raw / sub).exists() else 0
        print(f"  raw/{sub}: {n} file(s)")
    eb = _eb()
    lvl: dict[str, int] = {}
    for s in eb.studies:
        lvl[s.level.value] = lvl.get(s.level.value, 0) + 1
    print(f"  evidence base: {len(eb.studies)} studies {lvl}")


def cmd_demo(args) -> None:
    """Run objectives 1-6 end to end and write every artefact."""
    from .comparability import audit_table, comparability_matrix
    from .roadmap import build_roadmap, to_dataframe, to_markdown as rm_md
    from .strategy.agent import run_agent, trace_json
    from .synthetic import demo_dataset

    OUT.mkdir(exist_ok=True)
    print("[1/6] domain model -> JSON Schema")
    cmd_schema(args)

    print("[2/6] evidence base")
    eb = _eb()
    citable = [s for s in eb.studies if s.level.value != "to_verify"]
    print(f"      {len(eb.studies)} studies ({len(citable)} citable), "
          f"{sum(len(s.findings) for s in citable)} verified findings")

    print("[3/6] scenario -> candidate plan (agent)")
    st = run_agent(args.scenario, eb)
    (OUT / "strategy.md").write_text(st.report, encoding="utf-8")
    (OUT / "strategy_trace.json").write_text(trace_json(st), encoding="utf-8")
    print(f"      visits {st.proposal.sampling_days} · coverage {st.proposal.coverage} · "
          f"self-check {'pass' if st.critique.passed else 'FAIL'}")

    print("[5/6] synthetic demo dataset")
    df = demo_dataset(n=args.n, seed=args.seed)
    csv = ROOT / "data" / "synthetic" / "demo_kinetics.csv"
    csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv, index=False)
    print(f"      {len(df)} rows, {df['subject_id'].nunique()} subjects -> {csv}")

    print("[4/6] comparability + uncertainty")
    mat, details = comparability_matrix(df)
    bad = [k for k, v in details.items() if v.label == "not_comparable"]
    mat.to_csv(OUT / "comparability_matrix.csv")
    audit_table(df).to_csv(OUT / "data_audit.csv", index=False)
    print(f"      {len(mat)} series · {len(bad)} non-comparable pairs flagged")

    print("[6/6] roadmap")
    rm = build_roadmap(st, df)
    (OUT / "roadmap.md").write_text(rm_md(rm), encoding="utf-8")
    to_dataframe(rm).to_csv(OUT / "roadmap.csv", index=False)
    print(f"      {len(rm.tasks)} tasks")

    try:
        from .figures import comparability_heatmap, fold_rise_figure, kinetics_figure, uncertainty_figure

        for name, fig in [("kinetics", kinetics_figure(df, n_boot=80)),
                          ("fold_rise", fold_rise_figure(df)),
                          ("comparability", comparability_heatmap(mat)),
                          ("uncertainty", uncertainty_figure(df))]:
            fig.write_html(OUT / f"figure_{name}.html", include_plotlyjs="cdn")
        print("      figures -> outputs/figure_*.html")
    except ImportError:
        print("      (plotly not installed: skipped the HTML figures)")

    print(f"\nDone. Everything in {OUT}")
    print("Dashboard: python -m mvc.cli dashboard")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mvc", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("demo", help="run objectives 1-6 end to end")
    s.add_argument("--scenario", default=DEMO_SCENARIO)
    s.add_argument("-n", type=int, default=30)
    s.add_argument("--seed", type=int, default=42)
    s.set_defaults(func=cmd_demo)

    sub.add_parser("schema", help="export JSON Schema").set_defaults(func=cmd_schema)

    s = sub.add_parser("download", help="fetch public sources (needs Internet)")
    s.add_argument("--per-query", type=int, default=15)
    s.add_argument("--no-fulltext", action="store_true")
    s.set_defaults(func=cmd_download)

    s = sub.add_parser("build-evidence", help="raw -> extracted, quote-verified evidence")
    s.add_argument("--no-llm", action="store_true", help="force the deterministic rule extractor (fast)")
    s.add_argument("--limit", type=int, default=0, help="only process the first N documents")
    s.add_argument("--yes", action="store_true", help="skip the confirmation on a long LLM run")
    s.set_defaults(func=cmd_build_evidence)

    s = sub.add_parser("search", help="query the evidence base")
    s.add_argument("query")
    s.add_argument("-k", type=int, default=5)
    s.add_argument("--all", action="store_true", help="include non-citable chunks")
    s.set_defaults(func=cmd_search)

    sub.add_parser("graph", help="knowledge-graph stats and coverage gaps").set_defaults(func=cmd_graph)

    s = sub.add_parser("propose", help="scenario -> candidate plan")
    s.add_argument("scenario")
    s.add_argument("--print", action="store_true")
    s.set_defaults(func=cmd_propose)

    s = sub.add_parser("synth", help="write the synthetic dataset")
    s.add_argument("-n", type=int, default=30)
    s.add_argument("--seed", type=int, default=42)
    s.set_defaults(func=cmd_synth)

    sub.add_parser("dashboard", help="launch the Streamlit dashboard").set_defaults(func=cmd_dashboard)

    s = sub.add_parser("roadmap", help="90-day roadmap")
    s.add_argument("scenario", nargs="?", default=DEMO_SCENARIO)
    s.set_defaults(func=cmd_roadmap)

    sub.add_parser("eval", help="run the eval suite").set_defaults(func=cmd_eval)

    s = sub.add_parser("digitize", help="read data points off a figure (vision model)")
    s.add_argument("image")
    s.add_argument("--hint", default="")
    s.set_defaults(func=cmd_digitize)

    sub.add_parser("mcp", help="start the MCP server (stdio)").set_defaults(func=cmd_mcp)
    sub.add_parser("doctor", help="check the local environment").set_defaults(func=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
