"""Time management analytics for blunder detection."""

from __future__ import annotations

import statistics
from collections import defaultdict

from .models import MoveAnalysis, MoveFlag, ParsedGame, TimeControl, TimeStats

# Thresholds by time control category
_INSTA_THRESHOLDS: dict[str, float] = {
    "bullet": 1.0,
    "blitz": 2.0,
    "rapid": 3.0,
}

_TIME_TROUBLE_THRESHOLDS: dict[str, float] = {
    "bullet": 5.0,
    "blitz": 10.0,
    "rapid": 30.0,
}

_MIN_CLOCK_COVERAGE = 0.7


def _parse_time_control(tc_raw: str) -> tuple[int, int]:
    """Parse time control string into (initial_seconds, increment_seconds).

    Handles formats like "300", "300+5", "180+2", "600+0".
    Returns (0, 0) if unparseable.
    """
    try:
        if "+" in tc_raw:
            parts = tc_raw.split("+")
            return int(parts[0]), int(parts[1])
        return int(tc_raw), 0
    except (ValueError, IndexError):
        return 0, 0


def _tc_category(tc: TimeControl) -> str:
    """Map TimeControl enum to threshold category."""
    if tc == TimeControl.BULLET:
        return "bullet"
    if tc == TimeControl.BLITZ:
        return "blitz"
    if tc in (TimeControl.RAPID, TimeControl.DAILY):
        return "rapid"
    return "blitz"  # default fallback


def _compute_dt_s(
    analyses: list[MoveAnalysis], increment: int
) -> list[tuple[MoveAnalysis, float]]:
    """Derive time spent per move from clock timestamps.

    dt = previous_clock - current_clock + increment
    Returns list of (analysis, dt_seconds) pairs for moves where dt can be computed.
    """
    # Group by game and sort by ply
    by_game: dict[str, list[MoveAnalysis]] = defaultdict(list)
    for a in analyses:
        if a.is_player_move and a.clock_time is not None:
            by_game[a.game_id].append(a)

    results = []
    for game_id, moves in by_game.items():
        moves.sort(key=lambda m: m.ply)
        for i in range(1, len(moves)):
            prev_clock = moves[i - 1].clock_time
            curr_clock = moves[i].clock_time
            if prev_clock is None or curr_clock is None:
                continue
            dt = prev_clock - curr_clock + increment
            if dt < 0:
                dt = 0.0  # clock can reset on increment edge cases
            results.append((moves[i], dt))

    return results


def _is_time_trouble(clk_remain: float, tc_category: str) -> bool:
    """Check if remaining clock time indicates time trouble."""
    threshold = _TIME_TROUBLE_THRESHOLDS.get(tc_category, 10.0)
    return clk_remain <= threshold


def _is_insta_move(dt_s: float, tc_category: str) -> bool:
    """Check if move was played too fast (autopilot)."""
    threshold = _INSTA_THRESHOLDS.get(tc_category, 2.0)
    return dt_s <= threshold


def compute_time_stats(
    analyses: list[MoveAnalysis], games: list[ParsedGame]
) -> TimeStats | None:
    """Compute time management statistics.

    Returns None if clock coverage is insufficient (< 70%).
    """
    player_moves = [a for a in analyses if a.is_player_move]
    if not player_moves:
        return None

    # Check clock coverage
    moves_with_clock = sum(1 for a in player_moves if a.clock_time is not None)
    coverage = moves_with_clock / len(player_moves)
    if coverage < _MIN_CLOCK_COVERAGE:
        return None

    # Determine dominant time control for thresholds
    tc_counts: dict[TimeControl, int] = defaultdict(int)
    game_tc: dict[str, TimeControl] = {}
    game_tc_raw: dict[str, str] = {}
    for g in games:
        game_tc[g.game_id] = g.time_control
        game_tc_raw[g.game_id] = g.time_control_raw
        tc_counts[g.time_control] += 1

    dominant_tc = max(tc_counts, key=tc_counts.get) if tc_counts else TimeControl.BLITZ
    category = _tc_category(dominant_tc)

    # Parse increment from the most common time control
    # Use first game's raw TC as representative
    increment = 0
    if games:
        _, inc = _parse_time_control(games[0].time_control_raw)
        increment = inc

    # Compute dt_s for each move
    dt_pairs = _compute_dt_s(analyses, increment)
    if not dt_pairs:
        return None

    dt_values = [dt for _, dt in dt_pairs]
    avg_dt = statistics.mean(dt_values)
    median_dt = statistics.median(dt_values)
    p90_dt = sorted(dt_values)[int(len(dt_values) * 0.9)] if dt_values else 0.0

    # Classify moves
    insta_moves = []
    normal_moves = []
    time_trouble_count = 0

    for a, dt in dt_pairs:
        is_insta = _is_insta_move(dt, category)
        if is_insta:
            insta_moves.append((a, dt))
        else:
            normal_moves.append((a, dt))

        if a.clock_time is not None and _is_time_trouble(a.clock_time, category):
            time_trouble_count += 1

    # Blunder rates
    insta_blunders = sum(
        1 for a, _ in insta_moves if a.flag == MoveFlag.BLUNDER
    )
    normal_blunders = sum(
        1 for a, _ in normal_moves if a.flag == MoveFlag.BLUNDER
    )

    blunder_rate_insta = (
        insta_blunders / len(insta_moves) if insta_moves else 0.0
    )
    blunder_rate_normal = (
        normal_blunders / len(normal_moves) if normal_moves else 0.0
    )

    time_trouble_rate = time_trouble_count / len(dt_pairs) if dt_pairs else 0.0

    # Count autopilot blunders vs calculation failures
    autopilot_blunders = insta_blunders
    calculation_failures = sum(
        1 for a, dt in dt_pairs
        if a.flag == MoveFlag.BLUNDER and not _is_insta_move(dt, category)
        and dt > median_dt
    )

    return TimeStats(
        clock_coverage=coverage,
        avg_dt_s=avg_dt,
        median_dt_s=median_dt,
        p90_dt_s=p90_dt,
        time_trouble_rate=time_trouble_rate,
        blunder_rate_insta=blunder_rate_insta,
        blunder_rate_normal=blunder_rate_normal,
        autopilot_blunders=autopilot_blunders,
        calculation_failures=calculation_failures,
    )
