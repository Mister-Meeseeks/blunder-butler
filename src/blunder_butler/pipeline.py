"""Pipeline orchestrator: wires all stages and writes outputs."""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .aggregate import compute_summary
from .analyze import analyze_all_games
from .cache import write_games_jsonl, write_moves_jsonl
from .config import Config
from .fetch import fetch_games
from .llm import generate_report_with_llm_fallback
from .log import get_logger
from .models import RunMeta
from .parse import games_to_pgn, parse_games
from .phase import label_phases


def _git_commit_hash() -> str:
    """Get current git commit hash, or empty string."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _make_run_dir(config: Config) -> Path:
    """Create and return the output directory for this run."""
    run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(config.output_dir) / config.username / run_id
    for subdir in ["raw", "analysis", "stats", "report"]:
        (run_dir / subdir).mkdir(parents=True, exist_ok=True)
    return run_dir


def run_pipeline(config: Config) -> Path:
    """Execute the full analysis pipeline. Returns the run directory."""
    logger = get_logger()
    start_time = time.time()

    run_dir = _make_run_dir(config)
    run_id = run_dir.name
    logger.info("Output directory: %s", run_dir)

    # Stage 1: Fetch
    logger.info("=== Stage 1: Fetching games ===")
    raw_games, archive_urls = fetch_games(config)

    # Write raw archives
    archives_path = run_dir / "raw" / "archives.json"
    with open(archives_path, "w") as f:
        json.dump({"archives": archive_urls, "count": len(raw_games)}, f, indent=2)

    # Write raw PGN
    pgn_path = run_dir / "raw" / "games.pgn"
    pgn_text = games_to_pgn(raw_games)
    with open(pgn_path, "w") as f:
        f.write(pgn_text)

    # Stage 2: Parse
    logger.info("=== Stage 2: Parsing games ===")
    parsed_games = parse_games(raw_games, config.username)
    if not parsed_games:
        logger.warning("No games parsed successfully. Check username and filters.")
        # Still write metadata
        _write_run_meta(run_dir, config, run_id, start_time, 0, 0, 0, 0, 0)
        return run_dir

    logger.info("Parsed %d games", len(parsed_games))

    # Stage 3: Analyze
    logger.info("=== Stage 3: Analyzing with Stockfish ===")
    cache_path = run_dir / "analysis" / "cache.jsonl"
    analyses, cache_hits, cache_misses = analyze_all_games(parsed_games, config, cache_path)

    if not analyses:
        logger.warning("No positions analyzed. Check engine configuration.")
        _write_run_meta(
            run_dir, config, run_id, start_time,
            len(parsed_games), 0, 0, cache_hits, cache_misses,
        )
        return run_dir

    # Stage 4: Phase detection
    logger.info("=== Stage 4: Phase detection ===")
    analyses = label_phases(analyses)

    # Write analysis outputs
    moves_path = run_dir / "analysis" / "moves.jsonl"
    write_moves_jsonl(moves_path, analyses)

    # Stage 5: Aggregation
    logger.info("=== Stage 5: Aggregation ===")
    summary = compute_summary(analyses, parsed_games, config.username)

    # Write game summaries
    games_jsonl_path = run_dir / "analysis" / "games.jsonl"
    write_games_jsonl(games_jsonl_path, [gs.to_dict() for gs in summary.game_summaries])

    # Write summary
    summary_path = run_dir / "stats" / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary.to_dict(), f, indent=2)

    # Stage 6: Report
    logger.info("=== Stage 6: Report generation ===")
    from .llm import _build_evidence_packet
    evidence_path = run_dir / "report" / "evidence.json"
    with open(evidence_path, "w") as f:
        f.write(_build_evidence_packet(summary))
    report_text = generate_report_with_llm_fallback(summary, config)
    report_path = run_dir / "report" / "report.md"
    with open(report_path, "w") as f:
        f.write(report_text)

    # Write run metadata
    _write_run_meta(
        run_dir, config, run_id, start_time,
        len(parsed_games), len(parsed_games), len(analyses),
        cache_hits, cache_misses,
    )

    duration = time.time() - start_time
    logger.info("Pipeline complete in %.1fs", duration)
    logger.info("Report: %s", report_path)

    return run_dir


def _write_run_meta(
    run_dir: Path,
    config: Config,
    run_id: str,
    start_time: float,
    games_fetched: int,
    games_analyzed: int,
    positions_analyzed: int,
    cache_hits: int,
    cache_misses: int,
) -> None:
    """Write run.json metadata."""
    duration = time.time() - start_time
    meta = RunMeta(
        username=config.username,
        run_id=run_id,
        timestamp=datetime.utcnow().isoformat(),
        games_fetched=games_fetched,
        games_analyzed=games_analyzed,
        positions_analyzed=positions_analyzed,
        cache_hits=cache_hits,
        cache_misses=cache_misses,
        duration_seconds=duration,
        engine_settings=config.engine_settings_dict(),
        filters=config.filters_dict(),
        git_commit=_git_commit_hash(),
    )
    meta_path = run_dir / "run.json"
    with open(meta_path, "w") as f:
        json.dump(meta.to_dict(), f, indent=2)
