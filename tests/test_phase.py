"""Tests for phase detection."""

from __future__ import annotations

from blunder_butler.models import Phase
from blunder_butler.phase import detect_phase


def test_opening_early_ply():
    # Starting position, ply 1
    fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    assert detect_phase(fen, 1) == Phase.OPENING


def test_opening_undeveloped():
    # Ply 10, but minors still on home squares
    fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 5"
    assert detect_phase(fen, 10) == Phase.OPENING


def test_middlegame_developed():
    # Both sides developed, ply > 20
    fen = "r1bq1rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 4 8"
    assert detect_phase(fen, 22) == Phase.MIDDLEGAME


def test_middlegame_after_opening():
    # Developed position at ply 15
    fen = "r1bq1rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 4 8"
    assert detect_phase(fen, 15) == Phase.MIDDLEGAME


def test_endgame_low_material():
    # King + rook vs king + rook (material = 10, below threshold 13)
    fen = "4k3/8/8/8/8/8/8/R3K3 w Q - 0 40"
    assert detect_phase(fen, 60) == Phase.ENDGAME


def test_endgame_no_queens():
    # Rook endgame
    fen = "4k3/ppp2ppp/8/8/8/8/PPP2PPP/4K2R w K - 0 30"
    assert detect_phase(fen, 50) == Phase.ENDGAME


def test_not_endgame_with_queens():
    # Queens still on board = enough material
    fen = "r1bq1rk1/ppp2ppp/2n2n2/3pp3/3PP3/2N2N2/PPP2PPP/R1BQ1RK1 w - - 0 8"
    phase = detect_phase(fen, 30)
    assert phase != Phase.ENDGAME
