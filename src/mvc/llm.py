"""Minimal local-LLM client (Ollama HTTP API) — no SDK dependency.

Why Ollama: runs open-weight models on a CPU-only Windows laptop, offline,
no paid credits. Everything in the project works WITHOUT an LLM (rule-based
fallbacks); the LLM only adds: free-text scenario parsing, structured
extraction from papers, narrative explanations, figure digitisation (VLM).

Default models (override with env vars):
  MVC_LLM_MODEL    qwen2.5:3b        (~2 GB, ok on CPU)
  MVC_EMBED_MODEL  nomic-embed-text  (~270 MB)
  MVC_VLM_MODEL    qwen2.5vl:3b      (vision, optional)
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Any

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
LLM_MODEL = os.environ.get("MVC_LLM_MODEL", "qwen2.5:3b")
EMBED_MODEL = os.environ.get("MVC_EMBED_MODEL", "nomic-embed-text")
VLM_MODEL = os.environ.get("MVC_VLM_MODEL", "qwen2.5vl:3b")


class LLMUnavailable(RuntimeError):
    pass


def _post(path: str, payload: dict, timeout: float = 600) -> dict:
    req = urllib.request.Request(
        f"{OLLAMA_URL}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        raise LLMUnavailable(f"Ollama not reachable at {OLLAMA_URL}: {e}") from e


def is_available(model: str | None = None, timeout: float = 8.0) -> bool:
    """Is Ollama answering, and is `model` pulled?

    The timeout was 2 s, which is long enough when Ollama is idle and too short
    when it is not: the service stops answering /api/tags while it loads a
    model into memory, so this check failed exactly when another part of the
    app had just asked Ollama to warm up. A false "not available" is not a
    harmless default here — callers silently take their fallback path and keep
    it, so the cost of being wrong is asymmetric and the timeout should be
    generous.
    """
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=timeout) as r:
            tags = json.loads(r.read().decode())
    except Exception:
        return False
    if model is None:
        return True
    names = {m.get("name", "") for m in tags.get("models", [])}
    return any(n == model or n.startswith(model + ":") or n.split(":")[0] == model for n in names)


def chat(
    prompt: str,
    system: str = "",
    model: str | None = None,
    json_schema: dict | None = None,
    images: list[bytes] | None = None,
    temperature: float = 0.0,
) -> str:
    """One chat turn. With `json_schema`, Ollama constrains decoding to that schema."""
    msg: dict[str, Any] = {"role": "user", "content": prompt}
    if images:
        msg["images"] = [base64.b64encode(b).decode() for b in images]
    messages = ([{"role": "system", "content": system}] if system else []) + [msg]
    payload: dict[str, Any] = {
        "model": model or LLM_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature, "num_ctx": 8192},
    }
    if json_schema is not None:
        payload["format"] = json_schema
    return _post("/api/chat", payload)["message"]["content"]


def chat_json(prompt: str, schema: dict, system: str = "", **kw) -> dict:
    raw = chat(prompt, system=system, json_schema=schema, **kw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM did not return valid JSON: {raw[:200]}") from e


def embed(texts: list[str], model: str | None = None) -> list[list[float]]:
    out = _post("/api/embed", {"model": model or EMBED_MODEL, "input": texts})
    return out["embeddings"]
