"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from blunder_butler.config import Config
from blunder_butler.log import setup_logging
from blunder_butler.models import (
    Color,
    Eval,
    GameResult,
    MoveAnalysis,
    MoveFlag,
    ParsedGame,
    Phase,
    TimeControl,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _setup_logging():
    setup_logging(verbose=False)


@pytest.fixture
def sample_pgn_path() -> Path:
    return FIXTURES_DIR / "sample_3games.pgn"


@pytest.fixture
def default_config() -> Config:
    return Config(username="testplayer", engine_time_ms=100)


@pytest.fixture
def sample_parsed_game() -> ParsedGame:
    return ParsedGame(
        game_id="test123",
        white="testplayer",
        black="opponent1",
        result=GameResult.WIN,
        date="2024.01.15",
        time_control_raw="600",
        time_control=TimeControl.BLITZ,
        rated=True,
        player_color=Color.WHITE,
        moves_san=["e4", "e5", "Nf3", "Nc6", "Bc4"],
        fens=[
            "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
            "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
            "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2",
            "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3",
            "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3",
        ],
        clock_times=[None] * 5,
        url="https://www.chess.com/game/live/test123",
    )


@pytest.fixture
def sample_analyses() -> list[MoveAnalysis]:
    """Synthetic move analyses for testing aggregation."""
    analyses = []
    # 10 opening moves, 15 middlegame, 5 endgame
    for i in range(30):
        ply = i + 1
        if ply <= 10:
            phase = Phase.OPENING
        elif ply <= 25:
            phase = Phase.MIDDLEGAME
        else:
            phase = Phase.ENDGAME

        # Vary CPL: mostly good, a few mistakes/blunders
        if i == 5:
            cpl = 250  # blunder
            flag = MoveFlag.BLUNDER
        elif i == 12:
            cpl = 150  # mistake
            flag = MoveFlag.MISTAKE
        elif i == 18:
            cpl = 75  # inaccuracy
            flag = MoveFlag.INACCURACY
        elif i == 22:
            cpl = 300  # blunder
            flag = MoveFlag.BLUNDER
        else:
            cpl = 10
            flag = MoveFlag.GOOD

        analyses.append(MoveAnalysis(
            game_id="game1",
            ply=ply,
            move_san=f"move{ply}",
            move_uci=f"e2e{ply % 8 + 1}",
            fen_before="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            side_to_move=Color.WHITE if ply % 2 == 1 else Color.BLACK,
            eval_before=Eval(cp=50),
            best_move_uci="e2e4",
            best_move_san="e4",
            eval_best=Eval(cp=50),
            eval_after=Eval(cp=50 - cpl),
            cpl=cpl,
            flag=flag,
            pv=["e2e4"],
            phase=phase,
            is_player_move=True,
        ))
    return analyses
