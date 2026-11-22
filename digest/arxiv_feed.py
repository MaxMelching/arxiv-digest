"""Fetch and parse the daily arXiv announcement from the official RSS feed.

The feed at https://rss.arxiv.org/rss/<cat1>+<cat2>+... contains exactly the
papers of the most recent announcement (the same set as the mailing list),
with an <arxiv:announce_type> of new / cross / replace / replace-cross.
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime

import requests

RSS_URL = "https://rss.arxiv.org/rss/{cats}"
NS = {"arxiv": "http://arxiv.org/schemas/atom", "dc": "http://purl.org/dc/elements/1.1/"}
USER_AGENT = "arxiv-digest/1.0 (personal daily reading digest)"

_DESC_RE = re.compile(
    r"\s*arXiv:(?P<id>[^\s]+?)(?P<ver>v\d+)?\s+Announce Type:\s*\S+\s*(?:Abstract:\s*)?(?P<abs>.*)",
    re.S,
)
_AUTHOR_SPLIT = re.compile(r",\s*(?:and\s+)?|\s+and\s+")


@dataclass
class Paper:
    id: str  # arXiv id without version, e.g. "2611.24944"
    version: str
    title: str
    authors: list[str]
    abstract: str
    categories: list[str]  # first entry is the primary category
    announce_type: str
    # Filled in by ranking
    score: float = 0.0
    similar: list = field(default_factory=list)  # [(LibraryItem, similarity), ...]
    boosts: list = field(default_factory=list)  # human-readable boost reasons

    @property
    def primary(self) -> str:
        return self.categories[0] if self.categories else ""

    @property
    def abs_url(self) -> str:
        return f"https://arxiv.org/abs/{self.id}"

    @property
    def pdf_url(self) -> str:
        return f"https://arxiv.org/pdf/{self.id}"

    @property
    def html_url(self) -> str:
        return f"https://arxiv.org/html/{self.id}"

    def text(self, sep: str = "[SEP]") -> str:
        """Input format SPECTER was trained on: title [SEP] abstract."""
        return f"{self.title}{sep}{self.abstract}"


@dataclass
class Announcement:
    date: datetime | None  # the feed's pubDate (announcement date)
    papers: list[Paper]


def fetch_feed_xml(categories: list[str], retries: int = 3) -> str:
    url = RSS_URL.format(cats="+".join(categories))
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=60, headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:  # transient network / 5xx
            last_err = e
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"Could not fetch {url}: {last_err}")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def parse_feed(xml_text: str, announce_types: list[str] | None = None) -> Announcement:
    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("Not an RSS feed (no <channel>)")

    pub = channel.findtext("pubDate")
    date = parsedate_to_datetime(pub) if pub else None

    papers: dict[str, Paper] = {}
    for item in channel.findall("item"):
        atype = (item.findtext("arxiv:announce_type", "", NS) or "").strip()
        if announce_types and atype not in announce_types:
            continue

        desc = item.findtext("description") or ""
        m = _DESC_RE.match(desc)
        if m:
            aid, ver, abstract = m.group("id"), m.group("ver") or "", m.group("abs")
        else:  # unexpected format: fall back to the link
            link = item.findtext("link") or ""
            aid, ver, abstract = link.rstrip("/").rsplit("/", 1)[-1], "", desc
        aid = re.sub(r"v\d+$", "", aid)
        if aid in papers:
            continue

        creators = item.findtext("dc:creator", "", NS) or ""
        authors = [a.strip() for a in _AUTHOR_SPLIT.split(creators) if a.strip()]

        papers[aid] = Paper(
            id=aid,
            version=ver,
            title=_clean(item.findtext("title") or ""),
            authors=authors,
            abstract=_clean(abstract),
            categories=[_clean(c.text or "") for c in item.findall("category") if c.text],
            announce_type=atype,
        )

    return Announcement(date=date, papers=list(papers.values()))
