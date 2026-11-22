"""Embedding models and the on-disk cache for library embeddings."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numpy as np

from .zotero import LibraryItem


class SpecterEmbedder:
    """SPECTER via sentence-transformers. Runs locally; no API key needed."""

    def __init__(self, model_name: str = "sentence-transformers/allenai-specter"):
        from sentence_transformers import SentenceTransformer  # heavy import, keep lazy

        self.name = model_name
        self.model = SentenceTransformer(model_name, device="cpu")
        self.sep = getattr(self.model.tokenizer, "sep_token", None) or "[SEP]"

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.model.get_sentence_embedding_dimension()), np.float32)
        return self.model.encode(
            texts,
            batch_size=16,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        ).astype(np.float32)


class HashEmbedder:
    """Tiny bag-of-words stand-in for offline testing only (no model download)."""

    name = "hash-bow-test"
    sep = " "

    def __init__(self, dim: int = 4096):
        self.dim = dim

    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), np.float32)
        for i, t in enumerate(texts):
            for w in re.findall(r"[a-z][a-z\-]{2,}", t.lower()):
                h = int(hashlib.md5(w.encode()).hexdigest()[:8], 16)
                out[i, h % self.dim] += 1.0
        out = np.log1p(out)
        out /= np.linalg.norm(out, axis=1, keepdims=True) + 1e-9
        return out


def make_embedder(kind: str, model_name: str):
    return HashEmbedder() if kind == "hash" else SpecterEmbedder(model_name)


def embed_library(items: list[LibraryItem], embedder, cache_path: Path) -> np.ndarray:
    """Embed library items, re-encoding only items that are new or changed."""
    cached: dict[str, tuple[int, np.ndarray]] = {}
    if cache_path.exists():
        try:
            z = np.load(cache_path, allow_pickle=False)
            if str(z["model"]) == embedder.name:
                for k, v, e in zip(z["keys"], z["versions"], z["emb"]):
                    cached[str(k)] = (int(v), e)
        except Exception as e:  # corrupt / old cache: just rebuild
            print(f"[embed] ignoring unreadable cache ({e})")

    todo = [it for it in items if cached.get(it.key, (None,))[0] != it.version]
    print(f"[embed] library: {len(items)} items, {len(items) - len(todo)} cached, encoding {len(todo)}")
    if todo:
        new = embedder.encode([it.text(embedder.sep) for it in todo])
        for it, e in zip(todo, new):
            cached[it.key] = (it.version, e)

    emb = np.stack([cached[it.key][1] for it in items]).astype(np.float32)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(".tmp.npz")
    np.savez(
        tmp,
        model=np.array(embedder.name),
        keys=np.array([it.key for it in items]),
        versions=np.array([it.version for it in items], dtype=np.int64),
        emb=emb,
    )
    tmp.replace(cache_path)
    return emb
