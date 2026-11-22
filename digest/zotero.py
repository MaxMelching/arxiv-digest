"""Read your library (titles + abstracts) through the Zotero web API.

Needs ZOTERO_USER_ID (the numeric "userID" shown at zotero.org/settings/keys)
and ZOTERO_API_KEY (a read-only key is enough).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import requests

API = "https://api.zotero.org"
SKIP_TYPES = {"attachment", "note", "annotation"}


@dataclass
class LibraryItem:
    key: str
    version: int
    title: str
    abstract: str = ""
    url: str | None = None
    kind: str = "zotero"  # "zotero" | "interest" | "file"

    def text(self, sep: str = "[SEP]") -> str:
        return f"{self.title}{sep}{self.abstract}" if self.abstract else self.title


def _item_url(item: dict) -> str | None:
    d = item.get("data", {})
    if d.get("DOI"):
        return f"https://doi.org/{d['DOI']}"
    if d.get("url"):
        return d["url"]
    return item.get("links", {}).get("alternate", {}).get("href")


def _get(session: requests.Session, url: str, params: dict) -> requests.Response:
    for attempt in range(5):
        r = session.get(url, params=params, timeout=60)
        if r.status_code in (429, 503):  # rate limited: honour Retry-After
            time.sleep(int(r.headers.get("Retry-After", 5 * (attempt + 1))))
            continue
        r.raise_for_status()
        if "Backoff" in r.headers:
            time.sleep(int(r.headers["Backoff"]))
        return r
    r.raise_for_status()
    return r


def fetch_items(
    user_id: str,
    api_key: str,
    library_type: str = "user",
    collections: list[str] | None = None,
) -> list[LibraryItem]:
    base = f"{API}/{library_type}s/{user_id}"
    paths = (
        [f"{base}/collections/{c}/items/top" for c in collections]
        if collections
        else [f"{base}/items/top"]
    )
    s = requests.Session()
    s.headers.update({"Zotero-API-Key": api_key, "Zotero-API-Version": "3"})

    items: dict[str, LibraryItem] = {}
    for path in paths:
        start = 0
        while True:
            r = _get(s, path, {"format": "json", "limit": 100, "start": start})
            batch = r.json()
            for it in batch:
                d = it.get("data", {})
                if d.get("itemType") in SKIP_TYPES or not d.get("title"):
                    continue
                items[it["key"]] = LibraryItem(
                    key=it["key"],
                    version=int(it.get("version", d.get("version", 0))),
                    title=" ".join(d["title"].split()),
                    abstract=" ".join((d.get("abstractNote") or "").split()),
                    url=_item_url(it),
                )
            start += 100
            total = int(r.headers.get("Total-Results", 0))
            if not batch or start >= total:
                break
    return list(items.values())
