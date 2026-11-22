"""Render the digest as an HTML email (plus a plain-text fallback).

Email clients can't run MathJax, so TeX in titles/abstracts is converted to
Unicode (\\alpha -> α, M_\\odot -> M_⊙, ...) with pylatexenc.
"""
from __future__ import annotations

import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .arxiv_feed import Paper

TEMPLATES = Path(__file__).parent / "templates"
GMAIL_CLIP_BYTES = 98_000


@lru_cache(maxsize=1)
def _l2t():
    from pylatexenc.latex2text import LatexNodes2Text

    return LatexNodes2Text(math_mode="text", strict_latex_spaces=False)


def tex2text(s: str) -> str:
    """Best-effort TeX -> Unicode. Falls back to the raw string on any error."""
    if "\\" not in s and "$" not in s:
        return s.replace("~", "∼")
    # In plain-text abstracts '%', '&', '#' are literal and '~' means "approximately"
    pre = re.sub(r"(?<!\\)([%&#])", r"\\\1", s)
    pre = re.sub(r"(?<!\\)~", "∼", pre)
    try:
        out = _l2t().latex_to_text(pre)
    except Exception:
        return s
    out = re.sub(r"([_^])\s+", r"\1", out)  # "Ω_ GW" -> "Ω_GW"
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def format_authors(authors: list[str], max_n: int) -> str:
    if len(authors) <= max_n:
        return ", ".join(authors)
    return ", ".join(authors[: max_n - 1]) + f", … {authors[-1]} (+{len(authors) - max_n + 1} more)"


def _view(p: Paper, rank: int, cfg: dict, home: set[str]) -> dict:
    e = cfg.get("email", {})
    cross = p.primary not in home
    authors = [tex2text(a) for a in p.authors]  # names like G\"oksel -> Göksel
    return {
        "rank": rank,
        "id": p.id,
        "score": f"{p.score:.3f}",
        "title": tex2text(p.title),
        "authors": format_authors(authors, int(e.get("max_authors", 6))),
        "first_author": (authors[0].split()[-1] + (" et al." if len(authors) > 1 else "")) if authors else "",
        "abstract": tex2text(p.abstract),
        "primary": p.primary,
        "others": [c for c in p.categories[1:]],
        "cross": cross,
        "replaced": p.announce_type.startswith("replace"),
        "similar": [
            {"title": tex2text(it.title), "url": it.url, "sim": f"{s:.2f}", "interest": it.kind == "interest"}
            for it, s in p.similar
        ],
        "boosts": p.boosts,
        "abs_url": p.abs_url,
        "pdf_url": p.pdf_url,
        "html_url": p.html_url,
    }


def render(
    relevant: list[Paper],
    rest: list[Paper],
    date: datetime | None,
    cfg: dict,
    n_library: int,
) -> tuple[str, str, str]:
    home = set(cfg["categories"])
    day = (date or datetime.now()).strftime("%a %d %b %Y")
    subject = f"{cfg.get('email', {}).get('subject_prefix', 'arXiv digest')} · {day} · {len(relevant)} of {len(relevant) + len(rest)}"

    rest_views = [_view(p, len(relevant) + i + 1, cfg, home) for i, p in enumerate(rest)]
    ctx = {
        "subject": subject,
        "day": day,
        "categories": cfg["categories"],
        "n_total": len(relevant) + len(rest),
        "n_library": n_library,
        "relevant": [_view(p, i + 1, cfg, home) for i, p in enumerate(relevant)],
        "rest": rest_views,
        "n_rest": len(rest_views),
        "include_rest": cfg.get("email", {}).get("include_rest", True),
    }
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html", "j2"], default_for_string=False),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    tpl = env.get_template("email.html.j2")
    html = tpl.render(**ctx)
    # Gmail clips HTML bodies above ~102 KB. Shorten the below-cutoff list until it fits.
    while len(html.encode()) > GMAIL_CLIP_BYTES and ctx["rest"]:
        ctx["rest"] = ctx["rest"][: int(len(ctx["rest"]) * 0.85)]
        html = tpl.render(**ctx)

    env_txt = Environment(loader=FileSystemLoader(TEMPLATES), trim_blocks=True, lstrip_blocks=True, autoescape=False)
    text = env_txt.get_template("email.txt.j2").render(**{**ctx, "rest": rest_views})
    return subject, html, text
