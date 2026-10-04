#!/usr/bin/env python3
"""RUN THIS AT HOME, ON WIFI, BEFORE THE TRAIN.

It makes the whole project work offline:
  1. checks Python and installs the pip dependencies
  2. downloads a pip wheelhouse (so you can reinstall in the train with no network)
  3. fetches the public literature and trial registrations into data/raw/
  4. pulls the Ollama models (text, embeddings, vision) if Ollama is installed
  5. warms the embedding cache so retrieval works offline
  6. runs the test suite, the eval suite and the full demo as a final check

Usage:
    python scripts/download_pack.py              # everything
    python scripts/download_pack.py --skip-models
    python scripts/download_pack.py --only data  # steps: deps, wheels, data, models, cache, check
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

PIP_PACKAGES = [
    "pydantic>=2.6", "pandas>=2.1", "numpy>=1.26", "scipy>=1.11", "networkx>=3.2",
    "plotly>=5.20", "streamlit>=1.33", "pymupdf>=1.24", "pytest>=8.0",
]
OPTIONAL_PACKAGES = ["langgraph>=0.2", "mcp>=1.2"]
OLLAMA_MODELS = ["qwen2.5:3b", "nomic-embed-text", "qwen2.5vl:3b"]

OK, WARN, FAIL = "[ ok ]", "[warn]", "[FAIL]"


def say(tag: str, msg: str) -> None:
    print(f"{tag} {msg}", flush=True)


def run(cmd: list[str], **kw) -> int:
    say("  >", " ".join(cmd))
    return subprocess.call(cmd, **kw)


# --------------------------------------------------------------------------- #
def step_deps(args) -> bool:
    # ruff flags this as dead code because pyproject requires >=3.10. It is not:
    # this script is the first thing a user runs, on whatever interpreter is on
    # their PATH, before anything has checked their Python at all.
    if sys.version_info < (3, 10):  # noqa: UP036
        say(FAIL, f"Python {sys.version_info.major}.{sys.version_info.minor} — need 3.10+")
        return False
    say(OK, f"Python {sys.version.split()[0]}")
    code = run([sys.executable, "-m", "pip", "install", "--upgrade", *PIP_PACKAGES])
    if code:
        say(FAIL, "pip install failed for the required packages")
        return False
    for pkg in OPTIONAL_PACKAGES:
        if run([sys.executable, "-m", "pip", "install", pkg]):
            say(WARN, f"optional package {pkg} not installed (the project works without it)")
    say(OK, "dependencies installed")

    # Install the project itself. Without this, `python -m mvc.cli` fails with
    # "No module named 'mvc'" because the package lives under src/ — installing
    # the dependencies is not the same as installing the package.
    if run([sys.executable, "-m", "pip", "install", "-e", "."], cwd=ROOT):
        say(WARN, "editable install failed — falling back to PYTHONPATH for this run")
        say(WARN, f'set it yourself with:  $env:PYTHONPATH = "{SRC}"')
    else:
        say(OK, "project installed (editable) — `python -m mvc.cli` works from anywhere")

    # Verify, rather than assume.
    import os

    probe = run([sys.executable, "-c", "import mvc, sys; print('mvc', mvc.__version__)"],
                cwd=ROOT, env={**os.environ, "PYTHONPATH": str(SRC)})
    if probe:
        say(FAIL, "cannot import mvc even with PYTHONPATH set — check the src/ layout")
        return False
    say(OK, "import check passed")
    return True


def step_wheels(args) -> bool:
    """A local wheelhouse: lets you pip install in the train with no network."""
    out = ROOT / "vendor" / "wheels"
    out.mkdir(parents=True, exist_ok=True)
    code = run([sys.executable, "-m", "pip", "download", "-d", str(out), *PIP_PACKAGES])
    if code:
        say(WARN, "wheelhouse incomplete — not fatal, but offline reinstall may fail")
    n = len(list(out.glob("*")))
    (ROOT / "vendor" / "README.md").write_text(
        "# Offline wheelhouse\n\nReinstall with no network:\n\n"
        "    pip install --no-index --find-links vendor/wheels -r requirements.txt\n", encoding="utf-8")
    say(OK, f"{n} wheels in vendor/wheels")
    return True


def step_data(args) -> bool:
    sys.path.insert(0, str(SRC))
    try:
        from mvc.evidence.fetch import download_all
    except ImportError as e:
        say(FAIL, f"cannot import the project ({e}) — run the deps step first")
        return False
    try:
        m = download_all(per_query=args.per_query, fulltext=True)
    except Exception as e:
        say(FAIL, f"download failed: {e}")
        return False
    say(OK, f"{len(m['records'])} records · {len(m['fulltext'])} open-access full texts · "
            f"{len(m['trials'])} trial registrations")
    for err in m["errors"][:5]:
        say(WARN, err)

    # Extraction is NOT run here. It used to be, and on a corpus this size with a
    # local LLM it turned a download step into a multi-hour silent hang. It is a
    # separate, resumable command with its own progress output and cost warning.
    say(OK, "corpus cached — extraction is a separate step")
    print("    fast, deterministic:  python -m mvc.cli build-evidence --no-llm")
    print("    LLM, try a few first: python -m mvc.cli build-evidence --limit 5")
    print("    (the seed evidence base already works without either)")
    return True


def step_models(args) -> bool:
    if not shutil.which("ollama"):
        say(WARN, "Ollama not found. Install it from https://ollama.com (optional: "
                  "every feature has a rule-based fallback). Then re-run with --only models")
        return True
    for model in OLLAMA_MODELS:
        if run(["ollama", "pull", model]):
            say(WARN, f"could not pull {model}")
        else:
            say(OK, f"model {model} ready")
    return True


def step_cache(args) -> bool:
    """Warm the embedding cache so hybrid retrieval still works without Ollama."""
    sys.path.insert(0, str(SRC))
    try:
        from mvc import llm
        from mvc.evidence.search import HybridSearcher
        from mvc.evidence.store import chunks, load
    except ImportError as e:
        say(FAIL, f"cannot import the project ({e})")
        return False
    if not llm.is_available(llm.EMBED_MODEL):
        say(WARN, f"embedding model {llm.EMBED_MODEL} unavailable — retrieval will run BM25-only "
                  "(fine, just slightly weaker)")
        return True
    s = HybridSearcher(chunks(load()), use_embeddings=True)
    say(OK, f"embedding cache warmed · retrieval mode: {s.mode}")
    return True


def step_check(args) -> bool:
    sys.path.insert(0, str(SRC))
    ok = True
    env = {"PYTHONPATH": str(SRC)}
    import os

    full_env = {**os.environ, **env}
    if run([sys.executable, "-m", "pytest", "-q", str(ROOT / "tests")], env=full_env, cwd=ROOT):
        say(WARN, "some tests failed — look before you leave")
        ok = False
    else:
        say(OK, "test suite green")
    if run([sys.executable, "-m", "mvc.eval.run"], env=full_env, cwd=ROOT):
        say(WARN, "eval thresholds not met")
    else:
        say(OK, "eval suite green")
    if run([sys.executable, "-m", "mvc.cli", "demo"], env=full_env, cwd=ROOT):
        say(WARN, "demo failed")
        ok = False
    else:
        say(OK, "demo ran end to end -> outputs/")
    return ok


STEPS = {"deps": step_deps, "wheels": step_wheels, "data": step_data,
         "models": step_models, "cache": step_cache, "check": step_check}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=list(STEPS), help="run a single step")
    ap.add_argument("--skip-models", action="store_true")
    ap.add_argument("--skip-wheels", action="store_true")
    ap.add_argument("--per-query", type=int, default=20)
    args = ap.parse_args()

    order = [args.only] if args.only else [
        s for s in STEPS
        if not (s == "models" and args.skip_models) and not (s == "wheels" and args.skip_wheels)
    ]
    results = {}
    for name in order:
        print(f"\n=== {name} " + "=" * (60 - len(name)))
        results[name] = STEPS[name](args)

    print("\n=== summary " + "=" * 54)
    for name, ok in results.items():
        say(OK if ok else FAIL, name)
    manifest = ROOT / "data" / "raw" / "manifest.json"
    if manifest.exists():
        m = json.loads(manifest.read_text())
        say(OK, f"offline corpus: {len(m['records'])} papers, {len(m['trials'])} trials")
    print("\nIn the train, start with:  python -m mvc.cli doctor")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
