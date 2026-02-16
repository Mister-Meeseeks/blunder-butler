"""Single-game analysis pipeline with historical context."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

from .aggregate import (
    _compute_phase_stats,
    _detect_endgame_technique,
    _detect_hanging_pieces,
    _detect_ignored_threats,
    _detect_king_safety,
    _detect_material_givebacks,
    _detect_missed_tactics,
    _top_swing_moves,
)
from .analyze import analyze_game
from .cache import load_game_cache
from .config import Config
from .errors import BlunderButlerError
from .fetch import fetch_recent_games, fetch_single_game
from .log import get_logger
from .models import (
    MoveAnalysis,
    MoveFlag,
    ParsedGame,
    Phase,
    PhaseStats,
    SingleGameSummary,
    Summary,
)
from .parse import parse_game_from_api
from .phase import label_phases


# ---------------------------------------------------------------------------
# Game selector parsing
# ---------------------------------------------------------------------------

def parse_game_selector(selector: str) -> tuple[str, str]:
    """Parse a game selector string into (type, value).

    Returns one of:
      ("latest", "")
      ("offset", "-3")       # negative int string
      ("game_id", "144991567688")
      ("url", "https://...")
    """
    selector = selector.strip()
    if selector.lower() == "latest":
        return ("latest", "")
    if selector.startswith("https://") or selector.startswith("http://"):
        return ("url", selector)
    if re.match(r"^-\d+$", selector):
        return ("offset", selector)
    if re.match(r"^\d+$", selector):
        return ("game_id", selector)
    raise BlunderButlerError(
        f"Invalid game selector: '{selector}'. "
        "Use 'latest', a negative offset like '-3', a game ID, or a URL."
    )


def _game_id_from_url(url: str) -> str:
    """Extract game ID from a Chess.com game URL."""
    return url.rstrip("/").split("/")[-1]


# ---------------------------------------------------------------------------
# Historical context loading
# ---------------------------------------------------------------------------

def find_latest_run_dir(config: Config) -> Path | None:
    """Find the most recent bulk run directory for the user.

    Scans output_dir/{username}/ for YYYYMMDD_HHMMSS directories.
    Ignores single_* directories.
    """
    user_dir = Path(config.output_dir) / config.username
    if not user_dir.is_dir():
        return None

    run_dirs = []
    for d in user_dir.iterdir():
        if not d.is_dir():
            continue
        # Skip single-game output dirs
        if d.name.startswith("single_"):
            continue
        # Match YYYYMMDD_HHMMSS pattern
        if re.match(r"^\d{8}_\d{6}$", d.name):
            run_dirs.append(d)

    if not run_dirs:
        return None

    # Sort by name (timestamp) descending
    run_dirs.sort(key=lambda d: d.name, reverse=True)
    return run_dirs[0]


def load_historical_summary(config: Config) -> Summary | None:
    """Load the summary from the latest bulk run, or None if unavailable."""
    logger = get_logger()
    run_dir = find_latest_run_dir(config)
    if run_dir is None:
        logger.info("No historical run found for %s", config.username)
        return None

    summary_path = run_dir / "stats" / "summary.json"
    if not summary_path.exists():
        logger.info("No summary.json in %s", run_dir)
        return None

    try:
        data = json.loads(summary_path.read_text())
        # Reconstruct Summary from JSON — we only need the aggregate fields
        phase_stats = [
            PhaseStats(
                phase=Phase(ps["phase"]),
                total_moves=ps["total_moves"],
                acpl=ps["acpl"],
                blunders=ps["blunders"],
                mistakes=ps["mistakes"],
                inaccuracies=ps["inaccuracies"],
                blunders_per_100=ps.get("blunders_per_100", 0.0),
                mistakes_per_100=ps.get("mistakes_per_100", 0.0),
                inaccuracies_per_100=ps.get("inaccuracies_per_100", 0.0),
            )
            for ps in data.get("phase_stats", [])
        ]
        summary = Summary(
            username=data["username"],
            total_games=data["total_games"],
            total_moves=data["total_moves"],
            acpl=data["acpl"],
            phase_stats=phase_stats,
            time_control_stats=[],
            swing_moves=[],
            motifs=[],
        )
        logger.info(
            "Loaded historical context from %s (%d games, ACPL %.1f)",
            run_dir.name, summary.total_games, summary.acpl,
        )
        return summary
    except Exception as e:
        logger.warning("Failed to load historical summary: %s", e)
        return None


def resolve_and_fetch_game(selector: str, config: Config) -> ParsedGame:
    """Resolve a game selector and return the parsed game.

    For 'latest' and offset selectors, always fetches fresh games from the
    Chess.com API so that newly played games are immediately available.
    For game_id and URL selectors, tries cache first then API.
    """
    logger = get_logger()
    sel_type, sel_value = parse_game_selector(selector)

    if sel_type in ("latest", "offset"):
        return _resolve_by_recent_fetch(sel_type, sel_value, config)

    # For game_id / url, resolve the ID then look it up
    game_id = _game_id_from_url(sel_value) if sel_type == "url" else sel_value
    return _fetch_game_by_id(game_id, config)


def _resolve_by_recent_fetch(
    sel_type: str, sel_value: str, config: Config
) -> ParsedGame:
    """Fetch recent games from the API and pick by index."""
    logger = get_logger()
    max_fetch = 50 if sel_type == "latest" else abs(int(sel_value)) + 10

    logger.info("Fetching recent games from Chess.com API...")
    raw_games = fetch_recent_games(config.username, max_games=max_fetch)
    if not raw_games:
        raise BlunderButlerError(
            f"No games found on Chess.com for user '{config.username}'."
        )

    if sel_type == "latest":
        raw = raw_games[-1]
    else:
        offset = int(sel_value)  # negative, e.g. -3
        idx = len(raw_games) + offset
        if idx < 0 or idx >= len(raw_games):
            raise BlunderButlerError(
                f"Offset {offset} is out of range. "
                f"Only {len(raw_games)} recent games fetched."
            )
        raw = raw_games[idx]

    game = parse_game_from_api(raw, config.username)
    if game is None:
        raise BlunderButlerError("Failed to parse the selected game.")
    return game


def _fetch_game_by_id(game_id: str, config: Config) -> ParsedGame:
    """Find a game by ID: try fetch cache, then API."""
    logger = get_logger()

    # Try fetch cache first
    fetch_cache_path = Path(config.output_dir) / config.username.lower() / "fetch_cache.json"
    if fetch_cache_path.exists():
        try:
            data = json.loads(fetch_cache_path.read_text())
            for game_data in data.get("games", []):
                url = game_data.get("url", "")
                if url and url.rstrip("/").split("/")[-1] == game_id:
                    logger.info("Found game %s in fetch cache", game_id[:8])
                    game = parse_game_from_api(game_data, config.username)
                    if game:
                        return game
        except Exception as e:
            logger.debug("Failed to read fetch cache: %s", e)

    # Fetch from API
    logger.info("Fetching game %s from Chess.com API", game_id[:8])
    game_data = fetch_single_game(config.username, game_id)
    if game_data is None:
        raise BlunderButlerError(f"Game not found: {game_id}")
    game = parse_game_from_api(game_data, config.username)
    if game is None:
        raise BlunderButlerError(f"Failed to parse game: {game_id}")
    return game


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def get_or_analyze_game(
    game: ParsedGame, config: Config
) -> list[MoveAnalysis]:
    """Load cached analysis for a game, or run Stockfish if not cached."""
    logger = get_logger()

    # Try per-game cache
    if not config.no_game_cache:
        cached = load_game_cache(game.game_id, config)
        if cached is not None:
            return cached

    # Run engine analysis
    logger.info("Running Stockfish analysis for game %s (%d moves)",
                game.game_id[:8], len(game.moves_san))
    analyses, _, _ = analyze_game(game, config, cache={}, cache_path=None)
    return analyses


def compute_single_game_stats(
    analyses: list[MoveAnalysis],
    game: ParsedGame,
    historical_context: Summary | None = None,
) -> SingleGameSummary:
    """Compute aggregated stats for a single game."""
    player_moves = [a for a in analyses if a.is_player_move]
    n = len(player_moves)
    total_cpl = sum(m.cpl for m in player_moves)

    phase_stats = _compute_phase_stats(analyses)
    swing_moves = _top_swing_moves(analyses, [game], n=5)

    # Motif detection
    motifs = []
    for detector in [
        _detect_hanging_pieces,
        _detect_missed_tactics,
        _detect_ignored_threats,
        _detect_king_safety,
        _detect_endgame_technique,
        _detect_material_givebacks,
    ]:
        bucket = detector(analyses)
        if bucket.count > 0:
            motifs.append(bucket)

    return SingleGameSummary(
        game=game,
        analyses=analyses,
        phase_stats=phase_stats,
        swing_moves=swing_moves,
        motifs=motifs,
        historical_context=historical_context,
        total_moves=n,
        acpl=total_cpl / n if n > 0 else 0,
        blunders=sum(1 for m in player_moves if m.flag == MoveFlag.BLUNDER),
        mistakes=sum(1 for m in player_moves if m.flag == MoveFlag.MISTAKE),
        inaccuracies=sum(1 for m in player_moves if m.flag == MoveFlag.INACCURACY),
    )


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

SINGLE_GAME_SYSTEM_PROMPT = """You are an experienced chess coach following up on a recent game.

You previously wrote a comprehensive coaching report for this player based on their
recent games. Now the player has just finished a new game and wants your feedback on it.

Your job:
1. Review this specific game's key moments and turning points
2. Compare performance to the patterns you identified in your previous report
3. Note whether the player improved on issues you flagged, or repeated old patterns
4. Give specific, actionable advice for similar positions going forward

Keep it concise (500-800 words) and encouraging. Use Markdown formatting.
Address the player directly, as a continuation of your coaching relationship."""

SINGLE_GAME_SYSTEM_PROMPT_NO_HISTORY = """You are an experienced chess coach providing feedback on a single game.

You will receive detailed analysis of ONE game. Your job:
1. Analyze this specific game's key moments and turning points
2. Identify what went well and what could improve
3. Give specific, actionable advice for similar positions

Keep it concise (500-800 words) and encouraging. Use Markdown formatting."""


def _build_single_game_evidence(summary: SingleGameSummary) -> str:
    """Build a compact evidence packet for the LLM."""
    packet = summary.to_dict()

    # Add move-by-move detail for worst moves
    worst = sorted(
        [a for a in summary.analyses if a.is_player_move and a.cpl > 0],
        key=lambda a: a.cpl,
        reverse=True,
    )[:10]
    packet["worst_moves_detail"] = [
        {
            "ply": a.ply,
            "move_san": a.move_san,
            "best_move_san": a.best_move_san,
            "cpl": a.cpl,
            "flag": a.flag.value,
            "phase": a.phase.value,
            "eval_before": a.eval_before.to_dict(),
            "eval_after": a.eval_after.to_dict(),
            "fen_before": a.fen_before,
        }
        for a in worst
    ]

    return json.dumps(packet, indent=2)


def _load_historical_report(config: Config) -> str | None:
    """Load the report.md from the latest bulk run, or None."""
    run_dir = find_latest_run_dir(config)
    if run_dir is None:
        return None
    report_path = run_dir / "report" / "report.md"
    if not report_path.exists():
        return None
    return report_path.read_text()


def generate_single_game_report(
    summary: SingleGameSummary, config: Config
) -> str:
    """Generate a report for a single game, using LLM if enabled."""
    if config.llm == "on":
        llm_report = _generate_single_game_llm_report(summary, config)
        if llm_report:
            header = _game_header(summary)
            return header + llm_report.rstrip() + "\n\n---\n*Generated by Blunder Butler v0.1 (single-game analysis)*\n"
    return _generate_single_game_deterministic_report(summary)


def _game_header(summary: SingleGameSummary) -> str:
    """Build a structured header with game metadata."""
    g = summary.game
    lines = [
        f"# Game Analysis: {g.player_name} vs {g.opponent_name}",
        "",
        f"**Game:** [{g.game_id}]({g.url})" if g.url else f"**Game:** {g.game_id}",
        f"**Result:** {g.result.value.capitalize()}",
        f"**Color:** {g.player_color.value.capitalize()}",
        f"**Time Control:** {g.time_control.value.capitalize()}",
        f"**Date:** {g.date}",
    ]
    if g.eco:
        lines.append(f"**Opening:** {g.eco}")
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def _generate_single_game_llm_report(
    summary: SingleGameSummary, config: Config
) -> str | None:
    """Generate an LLM-powered single-game report using shared call_llm()."""
    from .llm import call_llm

    logger = get_logger()

    evidence = _build_single_game_evidence(summary)
    historical_report = _load_historical_report(config)

    if historical_report:
        system_prompt = SINGLE_GAME_SYSTEM_PROMPT
        user_prompt = (
            "Here is the coaching report you previously wrote for this player:\n\n"
            "---BEGIN PREVIOUS REPORT---\n"
            f"{historical_report}\n"
            "---END PREVIOUS REPORT---\n\n"
            "The player just finished a new game. Here is the detailed analysis:\n\n"
            f"{evidence}\n\n"
            "Please provide a follow-up review of this game, referencing your "
            "previous observations where relevant."
        )
    else:
        system_prompt = SINGLE_GAME_SYSTEM_PROMPT_NO_HISTORY
        user_prompt = (
            f"Analyze this single chess game and provide coaching feedback:\n\n{evidence}"
        )

    logger.info("LLM single-game request: evidence=%d chars, historical_report=%s",
                len(evidence), f"{len(historical_report)} chars" if historical_report else "none")

    return call_llm(system_prompt, user_prompt, config)


def _phase_label(phase: Phase) -> str:
    return phase.value.capitalize()


def _generate_single_game_deterministic_report(summary: SingleGameSummary) -> str:
    """Generate a deterministic Markdown report for a single game."""
    g = summary.game
    lines: list[str] = []

    lines.append(f"# Single Game Analysis: {g.player_name} vs {g.opponent_name}")
    lines.append("")
    lines.append(f"**Game:** [{g.game_id}]({g.url})" if g.url else f"**Game:** {g.game_id}")
    lines.append(f"**Result:** {g.result.value.capitalize()}")
    lines.append(f"**Color:** {g.player_color.value.capitalize()}")
    lines.append(f"**Time Control:** {g.time_control.value.capitalize()}")
    lines.append(f"**Date:** {g.date}")
    if g.eco:
        lines.append(f"**Opening:** {g.eco}")
    lines.append("")

    # Performance summary
    lines.append("## Performance")
    lines.append("")
    lines.append("| Metric | This Game |")
    lines.append("|--------|-----------|")
    lines.append(f"| Moves | {summary.total_moves} |")
    lines.append(f"| ACPL | {summary.acpl:.1f} |")
    lines.append(f"| Blunders | {summary.blunders} |")
    lines.append(f"| Mistakes | {summary.mistakes} |")
    lines.append(f"| Inaccuracies | {summary.inaccuracies} |")
    lines.append("")

    # Historical comparison
    if summary.historical_context:
        hc = summary.historical_context
        lines.append("### Compared to Your Baseline")
        lines.append("")
        lines.append(f"Your baseline over {hc.total_games} games: ACPL {hc.acpl:.1f}")
        lines.append("")
        diff = summary.acpl - hc.acpl
        if diff < -20:
            lines.append("This game was **significantly better** than your average.")
        elif diff < 0:
            lines.append("This game was **slightly better** than your average.")
        elif diff < 20:
            lines.append("This game was **about average** for you.")
        else:
            lines.append("This game was **worse than usual** for you.")
        lines.append("")

    # Phase breakdown
    active_phases = [ps for ps in summary.phase_stats if ps.total_moves > 0]
    if active_phases:
        lines.append("## Phase Breakdown")
        lines.append("")
        lines.append("| Phase | Moves | ACPL | Blunders | Mistakes |")
        lines.append("|-------|-------|------|----------|----------|")
        for ps in active_phases:
            lines.append(
                f"| {_phase_label(ps.phase)} | {ps.total_moves} | {ps.acpl:.1f} "
                f"| {ps.blunders} | {ps.mistakes} |"
            )
        lines.append("")

        # Phase comparison to baseline
        if summary.historical_context:
            hc_phases = {
                ps.phase: ps for ps in summary.historical_context.phase_stats
                if ps.total_moves > 0
            }
            for ps in active_phases:
                hc_ps = hc_phases.get(ps.phase)
                if hc_ps and ps.acpl > hc_ps.acpl + 30:
                    lines.append(
                        f"Your **{_phase_label(ps.phase).lower()}** was notably worse "
                        f"than your baseline ({ps.acpl:.0f} vs {hc_ps.acpl:.0f} ACPL)."
                    )
            lines.append("")

    # Key moments (swing moves)
    if summary.swing_moves:
        lines.append("## Key Moments")
        lines.append("")
        for i, sm in enumerate(summary.swing_moves, 1):
            move_num = (sm.ply + 1) // 2
            side = "..." if sm.ply % 2 == 0 else "."
            lines.append(
                f"{i}. **Move {move_num}{side}{sm.move_san}** ({_phase_label(sm.phase)}) — "
                f"{sm.cpl} CPL"
            )
            lines.append(f"   - Best was: {sm.best_move_san}")
            lines.append(f"   - Position: `{sm.fen_before}`")
            lines.append("")

    # Motifs
    if summary.motifs:
        lines.append("## Patterns")
        lines.append("")
        for motif in summary.motifs:
            lines.append(f"- **{motif.name}** ({motif.count}): {motif.description}")
        lines.append("")

    lines.append("---")
    lines.append("*Generated by Blunder Butler v0.1 (single-game analysis)*")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_single_game_pipeline(config: Config, game_selector: str) -> Path:
    """Execute the single-game analysis pipeline. Returns the output directory."""
    logger = get_logger()
    start_time = time.time()

    # 1. Resolve selector and fetch the game (always hits API for latest/offset)
    logger.info("=== Single Game Analysis ===")
    game = resolve_and_fetch_game(game_selector, config)

    logger.info(
        "Game: %s vs %s (%s as %s, %d moves)",
        game.white, game.black, game.result.value,
        game.player_color.value, len(game.moves_san),
    )

    # 2. Get/analyze moves (use cache or engine)
    analyses = get_or_analyze_game(game, config)
    if not analyses:
        raise BlunderButlerError(f"No moves analyzed for game {game.game_id}")

    # Phase detection
    analyses = label_phases(analyses)

    # 3. Load historical context
    historical = load_historical_summary(config)

    # 4. Compute single-game stats
    summary = compute_single_game_stats(analyses, game, historical)

    # 5. Write output
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(config.output_dir) / config.username / f"single_{game.game_id[:8]}_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Write summary.json
    summary_path = out_dir / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary.to_dict(), f, indent=2)

    # Write evidence.json
    evidence_path = out_dir / "evidence.json"
    with open(evidence_path, "w") as f:
        f.write(_build_single_game_evidence(summary))

    # 6. Generate reports
    # Always write the deterministic report as summary.md
    det_report = _generate_single_game_deterministic_report(summary)
    det_path = out_dir / "summary.md"
    with open(det_path, "w") as f:
        f.write(det_report)

    report_text = generate_single_game_report(summary, config)
    report_path = out_dir / "report.md"
    with open(report_path, "w") as f:
        f.write(report_text)

    duration = time.time() - start_time
    logger.info("Single-game analysis complete in %.1fs", duration)
    logger.info("Report: %s", report_path)

    return out_dir
