"""JSONL cache for engine analysis results."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

from .log import get_logger
from .models import MoveAnalysis

if TYPE_CHECKING:
    from .config import Config

CACHE_VERSION = "1"


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


def make_game_cache_key(game_id: str, config: Config) -> str:
    """Create a cache key for a full game from game_id and relevant config fields."""
    raw = "|".join([
        CACHE_VERSION,
        game_id,
        config.engine_settings_hash(),
        str(config.both_sides),
        str(config.inaccuracy_threshold),
        str(config.mistake_threshold),
        str(config.blunder_threshold),
    ])
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _game_cache_dir(config: Config) -> Path:
    """Return the directory for per-game cache files."""
    return Path(config.output_dir) / config.username.lower() / "game_cache"


def load_game_cache(game_id: str, config: Config) -> list[MoveAnalysis] | None:
    """Load cached game analysis. Returns None on miss."""
    logger = get_logger()
    key = make_game_cache_key(game_id, config)
    path = _game_cache_dir(config) / f"{key}.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        if data.get("cache_version") != CACHE_VERSION:
            return None
        analyses = [MoveAnalysis.from_dict(d) for d in data["analyses"]]
        logger.info("Game cache hit for %s (%d moves)", game_id[:8], len(analyses))
        return analyses
    except Exception as e:
        logger.warning("Error loading game cache for %s: %s", game_id[:8], e)
        return None


def save_game_cache(game_id: str, config: Config, analyses: list[MoveAnalysis]) -> None:
    """Save game analysis to the per-game cache."""
    logger = get_logger()
    cache_dir = _game_cache_dir(config)
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = make_game_cache_key(game_id, config)
    path = cache_dir / f"{key}.json"
    data = {
        "cache_version": CACHE_VERSION,
        "game_id": game_id,
        "analyses": [a.to_dict() for a in analyses],
    }
    try:
        with open(path, "w") as f:
            json.dump(data, f)
        logger.debug("Saved game cache for %s", game_id[:8])
    except Exception as e:
        logger.warning("Error saving game cache for %s: %s", game_id[:8], e)
