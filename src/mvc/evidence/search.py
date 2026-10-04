"""Hybrid retrieval: BM25 (lexical) + embeddings (semantic), fused with RRF.

* BM25 is implemented here in ~30 lines (no dependency) so you can read it.
* Dense retrieval uses Ollama embeddings when available; otherwise the
  searcher silently degrades to BM25 only (train mode, no network needed).
* Reciprocal Rank Fusion: score(d) = sum_r 1 / (k + rank_r(d)). Robust,
  parameter-light, no score calibration between retrievers needed.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass

import numpy as np

from .. import llm
from .store import ROOT, Chunk

CACHE = ROOT / "data" / "evidence" / ".embed_cache.json"

_STOP = set("""a an the of and or in on to for with by from at as is are was were be been this that these
those it its we our their which who than then not no but after before during between into over under
may might can could would should also both each such per via""".split())

SYNONYMS = {
    "iga": ["siga", "secretory", "mucosal"],
    "nasal": ["intranasal", "nose", "mucosa", "mucosal"],
    "serum": ["systemic", "blood", "igg"],
    "kinetics": ["timepoints", "peak", "durability", "waning"],
    "saliva": ["salivary", "oral"],
    "laiv": ["live", "attenuated", "flumist"],
    # "respond" and "response" stem to different roots ("respond" / "respons"),
    # so a question about whether participants *respond* missed findings phrased
    # as a "consistent response". Stemming cannot bridge that; domain vocabulary can.
    "respond": ["response", "responder", "consistent", "seroconversion"],
    "responder": ["response", "respond", "consistent"],
}


#: Conservative suffix-stripping rules, applied longest-first, once per token.
#: Without stemming, "compared across different trials" matched none of the
#: findings about "cross-trial comparisons" or "cross-study comparability" —
#: the most central query of this project scored zero. Morphology, not meaning,
#: was the obstacle. Rules are deliberately shallow: a real stemmer would also
#: conflate words this domain keeps distinct.
_SUFFIXES = [
    "ibility", "ability", "izations", "isations", "ization", "isation",
    "ations", "ation", "isons", "ison", "ments", "ment", "ness",
    "ively", "ively", "ible", "able", "ing", "edly", "ed", "ity", "ies", "es", "s",
]
_MIN_STEM = 4


def stem(word: str) -> str:
    """Reduce a word to a crude root, idempotently.

    Idempotence matters and is easy to get wrong: a single pass turned
    "response" into "respons", which a second pass then turned into "respon".
    A stemmer whose output depends on how many times it ran silently breaks
    every match where one side was stemmed twice — so this iterates to a fixed
    point instead, and `stem(stem(w)) == stem(w)` holds for every word.
    """
    for _ in range(5):
        before = word
        for suf in _SUFFIXES:
            if word.endswith(suf) and len(word) - len(suf) >= _MIN_STEM:
                word = word[: -len(suf)]
                if suf == "ies":
                    word += "y"
                break
        else:
            # "compare" -> "compar", so it meets "comparison"/"comparability"
            if len(word) > _MIN_STEM + 1 and word.endswith("e"):
                word = word[:-1]
        if word == before:
            break
    return word


def tokenize(text: str, apply_stem: bool = True) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", text.lower())
    toks = [t for t in toks if t not in _STOP and len(t) > 1]
    return [stem(t) for t in toks] if apply_stem else toks


#: The table above is written in plain words; both sides are stemmed once at
#: import so lookups keep working now that tokens are stemmed.
_SYNONYMS_STEMMED: dict[str, list[str]] = {
    stem(k): [stem(v) for v in vs] for k, vs in SYNONYMS.items()
}


def expand(tokens: list[str]) -> list[str]:
    out = list(tokens)
    for t in tokens:
        out += _SYNONYMS_STEMMED.get(t, [])
    return out


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.docs, self.k1, self.b = docs, k1, b
        self.N = len(docs)
        self.avgdl = sum(map(len, docs)) / max(self.N, 1)
        df = Counter(t for d in docs for t in set(d))
        self.idf = {t: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for t, n in df.items()}
        self.tf = [Counter(d) for d in docs]

    def scores(self, query: list[str]) -> np.ndarray:
        s = np.zeros(self.N)
        for i, (tf, d) in enumerate(zip(self.tf, self.docs)):
            norm = self.k1 * (1 - self.b + self.b * len(d) / self.avgdl)
            for q in query:
                if q in tf:
                    s[i] += self.idf[q] * tf[q] * (self.k1 + 1) / (tf[q] + norm)
        return s


@dataclass
class Hit:
    chunk: Chunk
    score: float
    ranks: dict[str, int]


#: Retrieval target weights by chunk kind.
#: A `finding` is the atomic, citable claim with its verbatim quote — that is
#: what a recommendation must cite. An `abstract` is long and therefore wins on
#: raw lexical overlap (it contains every word of the paper's claims at once),
#: which pushes the precise finding off the top of the list. Down-weighting
#: abstracts restores the intended ranking without touching the gold set: they
#: stay retrievable as context, but they no longer mask the claim they contain.
KIND_WEIGHTS = {"finding": 1.0, "abstract": 0.45}


class HybridSearcher:
    def __init__(self, chunks: list[Chunk], use_embeddings: bool | None = None, rrf_k: int = 60,
                 kind_weights: dict[str, float] | None = None):
        self.chunks = chunks
        self.rrf_k = rrf_k
        self.kind_weights = kind_weights or KIND_WEIGHTS
        self.bm25 = BM25([expand(tokenize(c.text + " " + " ".join(c.tags))) for c in chunks])
        if use_embeddings is None:
            use_embeddings = llm.is_available(llm.EMBED_MODEL)
        self.emb = self._embed_corpus() if use_embeddings else None

    # -- dense ---------------------------------------------------------------
    def _embed_corpus(self, batch_size: int = 16) -> np.ndarray | None:
        """Embed the corpus, cached on disk.

        Two things learned the hard way: embedding a few hundred passages on a
        CPU takes minutes, and a silent minute is indistinguishable from a
        crash — so progress goes to stderr. And the cache is flushed after
        every batch, not once at the end, so an interrupted run keeps the work
        it already paid for instead of starting over.
        """
        cache = {}
        if CACHE.exists():
            try:
                cache = json.loads(CACHE.read_text())
            except json.JSONDecodeError:
                cache = {}  # a run killed mid-write; recompute rather than crash
        keys = [hashlib.sha1((llm.EMBED_MODEL + c.text).encode()).hexdigest() for c in self.chunks]
        todo = [i for i, k in enumerate(keys) if k not in cache]

        if todo:
            n_batches = (len(todo) + batch_size - 1) // batch_size
            print(f"embedding {len(todo)} passages with {llm.EMBED_MODEL} "
                  f"({n_batches} batches, CPU — this is cached afterwards)",
                  file=sys.stderr, flush=True)
            t0 = time.time()
            try:
                for n, start in enumerate(range(0, len(todo), batch_size), start=1):
                    batch = todo[start:start + batch_size]
                    for i, v in zip(batch, llm.embed([self.chunks[i].text for i in batch])):
                        cache[keys[i]] = v
                    CACHE.write_text(json.dumps(cache))  # flush per batch
                    done = min(start + batch_size, len(todo))
                    elapsed = time.time() - t0
                    print(f"  batch {n}/{n_batches} · {done}/{len(todo)} passages · "
                          f"{elapsed:.0f}s elapsed, ~{elapsed / done * (len(todo) - done):.0f}s left",
                          file=sys.stderr, flush=True)
            except llm.LLMUnavailable:
                print("  embedding model unreachable — falling back to BM25 only",
                      file=sys.stderr, flush=True)
                return None
            except KeyboardInterrupt:
                print(f"\n  interrupted — {len(cache)} passages kept in the cache, "
                      "re-running resumes from there", file=sys.stderr, flush=True)
                raise

        m = np.array([cache[k] for k in keys], dtype=float)
        return m / np.linalg.norm(m, axis=1, keepdims=True)

    def _dense_scores(self, query: str) -> np.ndarray | None:
        if self.emb is None:
            return None
        try:
            q = np.array(llm.embed([query])[0], dtype=float)
        except llm.LLMUnavailable:
            return None
        return self.emb @ (q / np.linalg.norm(q))

    # -- fusion --------------------------------------------------------------
    def search(self, query: str, k: int = 5, citable_only: bool = False, tags: set[str] | None = None) -> list[Hit]:
        rankings: dict[str, np.ndarray] = {"bm25": self.bm25.scores(expand(tokenize(query)))}
        dense = self._dense_scores(query)
        if dense is not None:
            rankings["dense"] = dense
        fused = np.zeros(len(self.chunks))
        ranks_by_chunk: list[dict[str, int]] = [dict() for _ in self.chunks]
        for name, sc in rankings.items():
            order = np.argsort(-sc)
            for r, idx in enumerate(order):
                if name == "bm25" and sc[idx] <= 0:
                    continue
                w = self.kind_weights.get(self.chunks[idx].kind, 1.0)
                fused[idx] += w / (self.rrf_k + r + 1)
                ranks_by_chunk[idx][name] = r + 1
        if tags:
            fused += np.array([0.01 * len(tags & set(c.tags)) for c in self.chunks])
        hits = []
        for idx in np.argsort(-fused):
            c = self.chunks[idx]
            if fused[idx] <= 0:
                break
            if citable_only and not c.citable:
                continue
            hits.append(Hit(c, float(fused[idx]), ranks_by_chunk[idx]))
            if len(hits) >= k:
                break
        return hits

    @property
    def mode(self) -> str:
        return "hybrid (BM25 + embeddings)" if self.emb is not None else "BM25 only (no embedding model)"
