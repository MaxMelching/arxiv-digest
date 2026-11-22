"""Entry point:  python -m digest [--dry-run] [--force] ...

Pipeline: arXiv RSS -> Zotero library -> SPECTER embeddings -> rank -> email.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .arxiv_feed import fetch_feed_xml, parse_feed
from .embed import embed_library, make_embedder
from .rank import score_papers, split_at_cutoff
from .render import render
from .zotero import LibraryItem, fetch_items

MAX_FEED_AGE = timedelta(hours=36)


def load_library(cfg: dict, library_file: str | None) -> list[LibraryItem]:
    items: list[LibraryItem] = []
    uid, key = os.environ.get("ZOTERO_USER_ID"), os.environ.get("ZOTERO_API_KEY")
    z = cfg.get("zotero") or {}
    if library_file:
        for i, d in enumerate(json.loads(Path(library_file).read_text())):
            items.append(LibraryItem(key=f"file-{i}", version=0, title=d["title"],
                                     abstract=d.get("abstract", ""), url=d.get("url"), kind="file"))
    elif uid and key:
        items = fetch_items(uid, key, z.get("library_type", "user"), z.get("collections") or None)
        print(f"[zotero] {len(items)} items")
    else:
        print("[zotero] ZOTERO_USER_ID / ZOTERO_API_KEY not set; using only `interests` from config")

    for text in cfg.get("interests") or []:
        h = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
        items.append(LibraryItem(key=f"interest-{h:x}", version=h, title=text.strip(), kind="interest"))
    return items


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="digest")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--dry-run", action="store_true", help="render to --out but don't send email")
    ap.add_argument("--force", action="store_true", help="send even if this announcement was already sent")
    ap.add_argument("--feed-file", help="use a saved RSS XML file instead of fetching (testing)")
    ap.add_argument("--library-file", help="JSON list of {title, abstract} instead of Zotero (testing)")
    ap.add_argument("--embedder", choices=["specter", "hash"], default="specter",
                    help="'hash' is a tiny offline stand-in for testing")
    ap.add_argument("--cache-dir", default=".cache")
    ap.add_argument("--out", default="out")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(Path(args.config).read_text())
    cache, out = Path(args.cache_dir), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    state_file = cache / "state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}

    # 1. Today's announcement
    xml = Path(args.feed_file).read_text() if args.feed_file else fetch_feed_xml(cfg["categories"])
    ann = parse_feed(xml, cfg.get("announce_types"))
    stamp = ann.date.isoformat() if ann.date else None
    print(f"[arxiv] announcement {stamp}: {len(ann.papers)} papers")
    if not ann.papers:
        print("[arxiv] nothing announced; exiting")
        return 0
    if not args.force:
        if stamp and state.get("last_sent") == stamp:
            print("[arxiv] this announcement was already sent; exiting (use --force to resend)")
            return 0
        if ann.date and datetime.now(timezone.utc) - ann.date > MAX_FEED_AGE:
            print("[arxiv] feed is older than 36 h (holiday / weekend?); exiting")
            return 0

    # 2. Library + embeddings
    model_name = cfg.get("model", "sentence-transformers/allenai-specter")
    embedder = make_embedder(args.embedder, model_name)
    lib = load_library(cfg, args.library_file)
    if not lib:
        print("error: empty library — set Zotero secrets or add `interests` to config.yaml", file=sys.stderr)
        return 1
    lib_emb = embed_library(lib, embedder, cache / f"library_{embedder.name.replace('/', '_')}.npz")

    # 3. Rank
    paper_emb = embedder.encode([p.text(embedder.sep) for p in ann.papers])
    ranked = score_papers(ann.papers, paper_emb, lib, lib_emb, cfg)
    relevant, rest = split_at_cutoff(ranked, cfg)
    print(f"[rank] {len(relevant)} above cutoff; scores {ranked[0].score:.3f} … {ranked[-1].score:.3f}")

    # 4. Render + send
    subject, html, text = render(relevant, rest, ann.date, cfg, n_library=len(lib))
    (out / "digest.html").write_text(html, encoding="utf-8")
    (out / "digest.txt").write_text(text, encoding="utf-8")
    print(f"[render] {subject!r} ({len(html.encode()) / 1024:.0f} KB html) -> {out}/")

    if args.dry_run:
        print("[mail] dry run: not sending")
        return 0

    from .mailer import send

    send(subject, html, text)
    cache.mkdir(parents=True, exist_ok=True)
    state.update(last_sent=stamp, sent_at=datetime.now(timezone.utc).isoformat())
    state_file.write_text(json.dumps(state, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
