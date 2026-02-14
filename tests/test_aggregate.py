"""Tests for aggregation."""

from __future__ import annotations

from blunder_butler.aggregate import compute_summary
from blunder_butler.models import (
    Color,
    GameResult,
    MoveAnalysis,
    MoveFlag,
    ParsedGame,
    Phase,
    TimeControl,
)


def _make_game(game_id: str = "game1", tc: TimeControl = TimeControl.BLITZ) -> ParsedGame:
    return ParsedGame(
        game_id=game_id,
        white="testplayer",
        black="opponent",
        result=GameResult.WIN,
        date="2024.01.15",
        time_control_raw="600",
        time_control=tc,
        rated=True,
        player_color=Color.WHITE,
        moves_san=[],
        fens=[],
        clock_times=[],
        url="https://chess.com/game/live/" + game_id,
    )


def test_summary_acpl(sample_analyses):
    games = [_make_game()]
    summary = compute_summary(sample_analyses, games, "testplayer")
    assert summary.total_moves == 30
    assert summary.acpl > 0


def test_summary_phase_breakdown(sample_analyses):
    games = [_make_game()]
    summary = compute_summary(sample_analyses, games, "testplayer")
    phase_names = {ps.phase for ps in summary.phase_stats if ps.total_moves > 0}
    assert Phase.OPENING in phase_names
    assert Phase.MIDDLEGAME in phase_names
    assert Phase.ENDGAME in phase_names


def test_summary_blunder_count(sample_analyses):
    games = [_make_game()]
    summary = compute_summary(sample_analyses, games, "testplayer")
    total_blunders = sum(ps.blunders for ps in summary.phase_stats)
    assert total_blunders == 2  # ply 6 and ply 23


def test_summary_swing_moves(sample_analyses):
    games = [_make_game()]
    summary = compute_summary(sample_analyses, games, "testplayer")
    assert len(summary.swing_moves) > 0
    # Worst move should have highest CPL
    assert summary.swing_moves[0].cpl >= summary.swing_moves[-1].cpl


def test_summary_empty_analyses():
    games = [_make_game()]
    summary = compute_summary([], games, "testplayer")
    assert summary.total_moves == 0
    assert summary.acpl == 0


def test_summary_time_control_stats(sample_analyses):
    games = [_make_game()]
    summary = compute_summary(sample_analyses, games, "testplayer")
    assert len(summary.time_control_stats) >= 1
    blitz_stats = [tc for tc in summary.time_control_stats if tc.time_control == TimeControl.BLITZ]
    assert len(blitz_stats) == 1
    assert blitz_stats[0].games == 1


def test_game_summaries(sample_analyses):
    games = [_make_game()]
    summary = compute_summary(sample_analyses, games, "testplayer")
    assert len(summary.game_summaries) == 1
    gs = summary.game_summaries[0]
    assert gs.game_id == "game1"
    assert gs.total_moves == 30
