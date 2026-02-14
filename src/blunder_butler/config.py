"""Configuration dataclass with CLI defaults."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Config:
    """Frozen configuration for a pipeline run."""

    username: str = ""
    time_control: str = "all"  # bullet|blitz|rapid|daily|all
    since_days: int = 90
    since_date: str = ""  # YYYY-MM-DD override
    until_date: str = ""  # YYYY-MM-DD override
    max_games: int = 100
    rated_only: bool = True
    engine_time_ms: int = 100
    depth: int | None = None  # mutually exclusive with engine_time_ms
    engine_path: str = ""  # auto-detect if empty
    threads: int = 1
    hash_mb: int = 64
    both_sides: bool = False
    llm: str = "off"  # on|off
    llm_endpoint: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    resume: bool = False
    output_dir: str = "out"
    fetch_cache_ttl: int = 300  # seconds
    no_fetch_cache: bool = False
    workers: int = 4
    openings_only: bool = False
    endgames_only: bool = False
    inaccuracy_threshold: int = 50
    mistake_threshold: int = 100
    blunder_threshold: int = 200

    def engine_settings_hash(self) -> str:
        """Hash of engine settings for cache key derivation."""
        parts = [
            f"time_ms={self.engine_time_ms}",
            f"depth={self.depth}",
            f"threads={self.threads}",
            f"hash_mb={self.hash_mb}",
        ]
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def engine_settings_dict(self) -> dict:
        return {
            "engine_time_ms": self.engine_time_ms,
            "depth": self.depth,
            "threads": self.threads,
            "hash_mb": self.hash_mb,
            "engine_path": self.engine_path,
        }

    def filters_dict(self) -> dict:
        return {
            "time_control": self.time_control,
            "since_days": self.since_days,
            "since_date": self.since_date,
            "until_date": self.until_date,
            "max_games": self.max_games,
            "rated_only": self.rated_only,
            "both_sides": self.both_sides,
        }
