"""Game phase detection: opening / middlegame / endgame."""

from __future__ import annotations

import chess

from .models import MoveAnalysis, Phase

# Material values for phase detection (non-pawn)
PIECE_VALUES = {
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
}

# Endgame threshold: total non-pawn material for both sides combined
ENDGAME_MATERIAL_THRESHOLD = 13  # roughly no queens or equivalent


def _non_pawn_material(board: chess.Board) -> int:
    """Total non-pawn, non-king material for both sides."""
    total = 0
    for piece_type, value in PIECE_VALUES.items():
        total += len(board.pieces(piece_type, chess.WHITE)) * value
        total += len(board.pieces(piece_type, chess.BLACK)) * value
    return total


def _is_developed(board: chess.Board) -> bool:
    """Check if both sides have moved at least 2 minor pieces from starting squares."""
    white_minors_home = 0
    black_minors_home = 0

    # White minor starting squares: b1, c1, f1, g1
    white_minor_homes = {chess.B1, chess.C1, chess.F1, chess.G1}
    for sq in white_minor_homes:
        piece = board.piece_at(sq)
        if piece and piece.color == chess.WHITE and piece.piece_type in (chess.KNIGHT, chess.BISHOP):
            white_minors_home += 1

    # Black minor starting squares: b8, c8, f8, g8
    black_minor_homes = {chess.B8, chess.C8, chess.F8, chess.G8}
    for sq in black_minor_homes:
        piece = board.piece_at(sq)
        if piece and piece.color == chess.BLACK and piece.piece_type in (chess.KNIGHT, chess.BISHOP):
            black_minors_home += 1

    # Both sides have moved at least 2 minors
    white_developed = (4 - white_minors_home) >= 2
    black_developed = (4 - black_minors_home) >= 2
    return white_developed and black_developed


def detect_phase(fen: str, ply: int) -> Phase:
    """Detect the game phase for a given position and ply.

    Transitions are one-directional: OPENING -> MIDDLEGAME -> ENDGAME.
    This function classifies a single position; the caller should enforce monotonicity.
    """
    board = chess.Board(fen)
    material = _non_pawn_material(board)

    if material <= ENDGAME_MATERIAL_THRESHOLD:
        return Phase.ENDGAME

    # Opening: ply <= 20 AND not fully developed
    if ply <= 20 and not _is_developed(board):
        return Phase.OPENING

    return Phase.MIDDLEGAME


def label_phases(analyses: list[MoveAnalysis]) -> list[MoveAnalysis]:
    """Label each move analysis with its game phase, enforcing one-directional transitions.

    Groups by game_id and ensures monotonic phase progression within each game.
    """
    # Group by game
    by_game: dict[str, list[MoveAnalysis]] = {}
    for a in analyses:
        by_game.setdefault(a.game_id, []).append(a)

    for game_id, game_analyses in by_game.items():
        game_analyses.sort(key=lambda a: a.ply)
        current_phase = Phase.OPENING
        phase_order = {Phase.OPENING: 0, Phase.MIDDLEGAME: 1, Phase.ENDGAME: 2}

        for a in game_analyses:
            detected = detect_phase(a.fen_before, a.ply)
            # Enforce one-directional: can only advance or stay
            if phase_order[detected] >= phase_order[current_phase]:
                current_phase = detected
            a.phase = current_phase

    return analyses
