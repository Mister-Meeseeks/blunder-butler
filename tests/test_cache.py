"""Tests for cache read/write."""

from __future__ import annotations

from pathlib import Path

from blunder_butler.cache import load_cache, make_cache_key, write_cache_entry
from blunder_butler.models import Color, Eval, MoveAnalysis, MoveFlag, Phase


def _make_analysis() -> MoveAnalysis:
    return MoveAnalysis(
        game_id="test_game",
        ply=1,
        move_san="e4",
        move_uci="e2e4",
        fen_before="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        side_to_move=Color.WHITE,
        eval_before=Eval(cp=20),
        best_move_uci="e2e4",
        best_move_san="e4",
        eval_best=Eval(cp=20),
        eval_after=Eval(cp=20),
        cpl=0,
        flag=MoveFlag.BEST,
        pv=["e2e4"],
        phase=Phase.OPENING,
    )


def test_cache_key_deterministic():
    k1 = make_cache_key("fen1", "hash1")
    k2 = make_cache_key("fen1", "hash1")
    assert k1 == k2
    assert len(k1) == 16


def test_cache_key_varies():
    k1 = make_cache_key("fen1", "hash1")
    k2 = make_cache_key("fen2", "hash1")
    k3 = make_cache_key("fen1", "hash2")
    assert k1 != k2
    assert k1 != k3


def test_cache_roundtrip(tmp_path: Path):
    cache_path = tmp_path / "test_cache.jsonl"
    analysis = _make_analysis()
    key = "testkey12345678"

    write_cache_entry(cache_path, key, analysis)
    loaded = load_cache(cache_path)

    assert key in loaded
    cached = loaded[key]
    assert cached.game_id == "test_game"
    assert cached.move_san == "e4"
    assert cached.cpl == 0
    assert cached.flag == MoveFlag.BEST
    assert cached.eval_before.cp == 20


def test_cache_multiple_entries(tmp_path: Path):
    cache_path = tmp_path / "test_cache.jsonl"
    a1 = _make_analysis()
    a2 = _make_analysis()
    a2.ply = 2
    a2.move_san = "d4"

    write_cache_entry(cache_path, "key1_xxxxxxxxxxx", a1)
    write_cache_entry(cache_path, "key2_xxxxxxxxxxx", a2)

    loaded = load_cache(cache_path)
    assert len(loaded) == 2


def test_cache_empty_file(tmp_path: Path):
    cache_path = tmp_path / "nonexistent.jsonl"
    loaded = load_cache(cache_path)
    assert len(loaded) == 0
