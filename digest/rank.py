"""Score today's papers against your library and decide the relevance cutoff."""
from __future__ import annotations

import re

import numpy as np

from .arxiv_feed import Paper
from .zotero import LibraryItem


def score_papers(
    papers: list[Paper],
    paper_emb: np.ndarray,
    lib_items: list[LibraryItem],
    lib_emb: np.ndarray,
    cfg: dict,
) -> list[Paper]:
    """Score = mean cosine similarity to your k most similar saved papers (+ boosts).

    Using the k nearest neighbours (rather than the library average) keeps
    distinct interests separate: a paper only needs to be close to *one*
    cluster of your library to score well.
    """
    r = cfg.get("ranking", {})
    k = max(1, min(int(r.get("top_k", 5)), len(lib_items)))
    n_show = int(cfg.get("email", {}).get("show_similar", 2))

    sims = paper_emb @ lib_emb.T  # embeddings are L2-normalised -> cosine
    order = np.argsort(-sims, axis=1)[:, :k]
    base = np.take_along_axis(sims, order, axis=1).mean(axis=1)

    boosts = r.get("boosts") or {}
    author_boosts = {a.lower(): float(w) for a, w in (boosts.get("authors") or {}).items()}
    kw_boosts = {kw: float(w) for kw, w in (boosts.get("keywords") or {}).items()}

    for i, p in enumerate(papers):
        p.score = float(base[i])
        p.similar = [(lib_items[j], float(sims[i, j])) for j in order[i, :n_show]]
        p.boosts = []
        names = [a.lower() for a in p.authors]
        for a, w in author_boosts.items():
            if any(a in n for n in names):
                p.score += w
                p.boosts.append(f"author: {a.title()}")
        hay = f"{p.title} {p.abstract}"
        for kw, w in kw_boosts.items():
            if re.search(rf"(?<!\w){re.escape(kw)}", hay, re.I):
                p.score += w
                p.boosts.append(f"keyword: {kw}")

    return sorted(papers, key=lambda p: p.score, reverse=True)


def split_at_cutoff(ranked: list[Paper], cfg: dict) -> tuple[list[Paper], list[Paper]]:
    c = cfg.get("ranking", {}).get("cutoff", {})
    lo, hi = int(c.get("min", 5)), int(c.get("max", 25))
    min_score = c.get("min_score")
    if min_score is not None:
        n = sum(p.score >= float(min_score) for p in ranked)
    else:
        n = round(float(c.get("fraction", 0.2)) * len(ranked))
    n = max(lo, min(hi, n, len(ranked))) if ranked else 0
    n = min(n, len(ranked))
    return ranked[:n], ranked[n:]
