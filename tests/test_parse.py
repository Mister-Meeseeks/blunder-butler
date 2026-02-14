"""Tests for PGN parsing."""

from __future__ import annotations

from blunder_butler.models import Color, GameResult, TimeControl
from blunder_butler.parse import parse_game_from_api


def _make_game_data(pgn: str, **kwargs) -> dict:
    base = {"pgn": pgn, "url": "https://www.chess.com/game/live/99999", "rated": True}
    base.update(kwargs)
    return base


SAMPLE_PGN = """[Event "Live Chess"]
[Site "Chess.com"]
[Date "2024.01.15"]
[White "testplayer"]
[Black "opponent1"]
[Result "1-0"]
[TimeControl "600"]
[ECO "C50"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. O-O Nf6 5. d3 d6 1-0
"""


def test_parse_basic_game():
    data = _make_game_data(SAMPLE_PGN, time_control="600")
    game = parse_game_from_api(data, "testplayer")
    assert game is not None
    assert game.white == "testplayer"
    assert game.black == "opponent1"
    assert game.player_color == Color.WHITE
    assert game.result == GameResult.WIN
    assert len(game.moves_san) == 10
    assert len(game.fens) == 10
    assert game.moves_san[0] == "e4"
    assert game.moves_san[-1] == "d6"


def test_parse_black_player():
    pgn = SAMPLE_PGN.replace("testplayer", "SOMEONE").replace("opponent1", "testplayer")
    pgn = pgn.replace("SOMEONE", "opponent1")
    data = _make_game_data(pgn, time_control="600")
    game = parse_game_from_api(data, "testplayer")
    assert game is not None
    assert game.player_color == Color.BLACK
    assert game.result == GameResult.LOSS


def test_parse_time_control_classification():
    # Blitz (300s = 5 min)
    data = _make_game_data(SAMPLE_PGN, time_control="300")
    game = parse_game_from_api(data, "testplayer")
    assert game is not None
    assert game.time_control == TimeControl.BLITZ

    # Rapid (600s = 10 min, >= 600 threshold)
    data = _make_game_data(SAMPLE_PGN, time_control="600")
    game = parse_game_from_api(data, "testplayer")
    assert game is not None
    assert game.time_control == TimeControl.RAPID

    # Bullet (60s)
    data = _make_game_data(SAMPLE_PGN, time_control="60")
    game = parse_game_from_api(data, "testplayer")
    assert game is not None
    assert game.time_control == TimeControl.BULLET


def test_parse_empty_pgn():
    data = _make_game_data("")
    game = parse_game_from_api(data, "testplayer")
    assert game is None


def test_parse_unknown_username():
    data = _make_game_data(SAMPLE_PGN)
    game = parse_game_from_api(data, "nobody")
    assert game is None


def test_parse_draw_result():
    pgn = SAMPLE_PGN.replace("1-0", "1/2-1/2")
    data = _make_game_data(pgn, time_control="600")
    game = parse_game_from_api(data, "testplayer")
    assert game is not None
    assert game.result == GameResult.DRAW
