"""JSONL cache for engine analysis results."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .log import get_logger
from .models import MoveAnalysis


def make_cache_key(fen: str, engine_hash: str) -> str:
    """Create a cache key from FEN and engine settings hash."""
    raw = f"{fen}|{engine_hash}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def load_cache(cache_path: Path) -> dict[str, MoveAnalysis]:
    """Load cached analysis from a JSONL file. Returns {cache_key: MoveAnalysis}."""
    logger = get_logger()
    cache: dict[str, MoveAnalysis] = {}
    if not cache_path.exists():
        return cache
    try:
        with open(cache_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                key = entry.get("_cache_key", "")
                if key:
                    cache[key] = MoveAnalysis.from_dict(entry)
    except Exception as e:
        logger.warning("Error loading cache from %s: %s", cache_path, e)
    logger.info("Loaded %d cached positions from %s", len(cache), cache_path)
    return cache


def write_cache_entry(cache_path: Path, cache_key: str, analysis: MoveAnalysis) -> None:
    """Append a single analysis entry to the JSONL cache."""
    entry = analysis.to_dict()
    entry["_cache_key"] = cache_key
    with open(cache_path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def write_moves_jsonl(path: Path, analyses: list[MoveAnalysis]) -> None:
    """Write all move analyses to a JSONL file."""
    with open(path, "w") as f:
        for a in analyses:
            f.write(json.dumps(a.to_dict()) + "\n")


def write_games_jsonl(path: Path, game_summaries: list[dict]) -> None:
    """Write game summaries to a JSONL file."""
    with open(path, "w") as f:
        for gs in game_summaries:
            f.write(json.dumps(gs) + "\n")
