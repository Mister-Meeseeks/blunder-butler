"""Data models for Blunder Butler."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class TimeControl(enum.Enum):
    BULLET = "bullet"
    BLITZ = "blitz"
    RAPID = "rapid"
    DAILY = "daily"
    UNKNOWN = "unknown"


class GameResult(enum.Enum):
    WIN = "win"
    LOSS = "loss"
    DRAW = "draw"


class Phase(enum.Enum):
    OPENING = "opening"
    MIDDLEGAME = "middlegame"
    ENDGAME = "endgame"


class MoveFlag(enum.Enum):
    BEST = "best"
    GOOD = "good"
    INACCURACY = "inaccuracy"
    MISTAKE = "mistake"
    BLUNDER = "blunder"


class Color(enum.Enum):
    WHITE = "white"
    BLACK = "black"


@dataclass
class Eval:
    """Engine evaluation: either centipawns or mate distance."""

    cp: int | None = None
    mate: int | None = None

    @property
    def is_mate(self) -> bool:
        return self.mate is not None

    def to_cp_clamped(self, clamp: int = 1500) -> int:
        """Convert to centipawn value, clamping mates to ±clamp."""
        if self.mate is not None:
            return clamp if self.mate > 0 else -clamp
        return max(-clamp, min(clamp, self.cp or 0))

    def to_dict(self) -> dict:
        if self.mate is not None:
            return {"mate": self.mate}
        return {"cp": self.cp or 0}

    @classmethod
    def from_dict(cls, d: dict) -> Eval:
        if "mate" in d and d["mate"] is not None:
            return cls(mate=d["mate"])
        return cls(cp=d.get("cp", 0))


@dataclass
class ParsedGame:
    """A parsed chess game from PGN."""

    game_id: str
    white: str
    black: str
    result: GameResult
    date: str
    time_control_raw: str
    time_control: TimeControl
    rated: bool
    player_color: Color
    moves_san: list[str]
    fens: list[str]  # FEN after each ply (index 0 = after move 1 white)
    clock_times: list[float | None]  # clock seconds remaining, if available
    url: str = ""
    eco: str = ""

    @property
    def player_name(self) -> str:
        return self.white if self.player_color == Color.WHITE else self.black

    @property
    def opponent_name(self) -> str:
        return self.black if self.player_color == Color.WHITE else self.white


@dataclass
class MoveAnalysis:
    """Per-move analysis record."""

    game_id: str
    ply: int  # 1-indexed
    move_san: str
    move_uci: str
    fen_before: str
    side_to_move: Color
    eval_before: Eval
    best_move_uci: str
    best_move_san: str
    eval_best: Eval
    eval_after: Eval
    cpl: int  # centipawn loss (from player perspective), >= 0
    flag: MoveFlag
    pv: list[str]  # principal variation (UCI moves)
    phase: Phase = Phase.MIDDLEGAME
    is_player_move: bool = True
    clock_time: float | None = None

    def to_dict(self) -> dict:
        return {
            "game_id": self.game_id,
            "ply": self.ply,
            "move_san": self.move_san,
            "move_uci": self.move_uci,
            "fen_before": self.fen_before,
            "side_to_move": self.side_to_move.value,
            "eval_before": self.eval_before.to_dict(),
            "best_move_uci": self.best_move_uci,
            "best_move_san": self.best_move_san,
            "eval_best": self.eval_best.to_dict(),
            "eval_after": self.eval_after.to_dict(),
            "cpl": self.cpl,
            "flag": self.flag.value,
            "pv": self.pv,
            "phase": self.phase.value,
            "is_player_move": self.is_player_move,
            "clock_time": self.clock_time,
        }

    @classmethod
    def from_dict(cls, d: dict) -> MoveAnalysis:
        return cls(
            game_id=d["game_id"],
            ply=d["ply"],
            move_san=d["move_san"],
            move_uci=d["move_uci"],
            fen_before=d["fen_before"],
            side_to_move=Color(d["side_to_move"]),
            eval_before=Eval.from_dict(d["eval_before"]),
            best_move_uci=d["best_move_uci"],
            best_move_san=d["best_move_san"],
            eval_best=Eval.from_dict(d["eval_best"]),
            eval_after=Eval.from_dict(d["eval_after"]),
            cpl=d["cpl"],
            flag=MoveFlag(d["flag"]),
            pv=d["pv"],
            phase=Phase(d.get("phase", "middlegame")),
            is_player_move=d.get("is_player_move", True),
            clock_time=d.get("clock_time"),
        )


@dataclass
class SwingMove:
    """A move with a large eval swing (worst moves)."""

    game_id: str
    ply: int
    move_san: str
    fen_before: str
    best_move_san: str
    cpl: int
    eval_before: Eval
    eval_after: Eval
    pv: list[str]
    phase: Phase
    game_url: str = ""

    def to_dict(self) -> dict:
        return {
            "game_id": self.game_id,
            "ply": self.ply,
            "move_san": self.move_san,
            "fen_before": self.fen_before,
            "best_move_san": self.best_move_san,
            "cpl": self.cpl,
            "eval_before": self.eval_before.to_dict(),
            "eval_after": self.eval_after.to_dict(),
            "pv": self.pv,
            "phase": self.phase.value,
            "game_url": self.game_url,
        }


@dataclass
class PhaseStats:
    """Aggregated stats for a game phase."""

    phase: Phase
    total_moves: int = 0
    acpl: float = 0.0
    blunders: int = 0
    mistakes: int = 0
    inaccuracies: int = 0
    blunders_per_100: float = 0.0
    mistakes_per_100: float = 0.0
    inaccuracies_per_100: float = 0.0

    def to_dict(self) -> dict:
        return {
            "phase": self.phase.value,
            "total_moves": self.total_moves,
            "acpl": round(self.acpl, 1),
            "blunders": self.blunders,
            "mistakes": self.mistakes,
            "inaccuracies": self.inaccuracies,
            "blunders_per_100": round(self.blunders_per_100, 1),
            "mistakes_per_100": round(self.mistakes_per_100, 1),
            "inaccuracies_per_100": round(self.inaccuracies_per_100, 1),
        }


@dataclass
class MotifExample:
    """An example position illustrating a weakness motif."""

    game_id: str
    ply: int
    fen: str
    move_san: str
    best_move_san: str
    eval_swing: int
    pv: list[str]
    game_url: str = ""
    subtype: str = ""
    confidence: float = 0.0
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "game_id": self.game_id,
            "ply": self.ply,
            "fen": self.fen,
            "move_san": self.move_san,
            "best_move_san": self.best_move_san,
            "eval_swing": self.eval_swing,
            "pv": self.pv,
            "game_url": self.game_url,
        }
        if self.subtype:
            d["subtype"] = self.subtype
            d["confidence"] = round(self.confidence, 2)
        if self.meta:
            d["meta"] = self.meta
        return d


@dataclass
class MotifBucket:
    """A weakness motif with evidence examples."""

    name: str
    description: str
    count: int = 0
    examples: list[MotifExample] = field(default_factory=list)
    subtype_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "description": self.description,
            "count": self.count,
            "examples": [e.to_dict() for e in self.examples],
        }
        if self.subtype_counts:
            d["subtype_counts"] = self.subtype_counts
        return d


@dataclass
class GameSummary:
    """Per-game summary after analysis."""

    game_id: str
    player_color: Color
    result: GameResult
    time_control: TimeControl
    opponent: str
    total_moves: int
    acpl: float
    blunders: int
    mistakes: int
    inaccuracies: int
    url: str = ""
    date: str = ""

    def to_dict(self) -> dict:
        return {
            "game_id": self.game_id,
            "player_color": self.player_color.value,
            "result": self.result.value,
            "time_control": self.time_control.value,
            "opponent": self.opponent,
            "total_moves": self.total_moves,
            "acpl": round(self.acpl, 1),
            "blunders": self.blunders,
            "mistakes": self.mistakes,
            "inaccuracies": self.inaccuracies,
            "url": self.url,
            "date": self.date,
        }


@dataclass
class TimeControlStats:
    """Stats broken down by time control."""

    time_control: TimeControl
    games: int = 0
    total_moves: int = 0
    acpl: float = 0.0
    blunders_per_100: float = 0.0
    mistakes_per_100: float = 0.0

    def to_dict(self) -> dict:
        return {
            "time_control": self.time_control.value,
            "games": self.games,
            "total_moves": self.total_moves,
            "acpl": round(self.acpl, 1),
            "blunders_per_100": round(self.blunders_per_100, 1),
            "mistakes_per_100": round(self.mistakes_per_100, 1),
        }


@dataclass
class RunMeta:
    """Metadata about a pipeline run."""

    username: str
    run_id: str
    timestamp: str
    games_fetched: int = 0
    games_analyzed: int = 0
    positions_analyzed: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    duration_seconds: float = 0.0
    engine_settings: dict = field(default_factory=dict)
    filters: dict = field(default_factory=dict)
    git_commit: str = ""

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "games_fetched": self.games_fetched,
            "games_analyzed": self.games_analyzed,
            "positions_analyzed": self.positions_analyzed,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "duration_seconds": round(self.duration_seconds, 2),
            "engine_settings": self.engine_settings,
            "filters": self.filters,
            "git_commit": self.git_commit,
        }


@dataclass
class TimeStats:
    """Time usage statistics."""

    clock_coverage: float  # fraction of moves with clock data
    avg_dt_s: float
    median_dt_s: float
    p90_dt_s: float
    time_trouble_rate: float  # fraction of moves in time trouble
    blunder_rate_insta: float  # blunder rate on fast moves
    blunder_rate_normal: float  # blunder rate on non-fast moves
    autopilot_blunders: int  # count of fast-move blunders
    calculation_failures: int  # count of slow-move blunders

    def to_dict(self) -> dict:
        return {
            "clock_coverage": round(self.clock_coverage, 3),
            "avg_dt_s": round(self.avg_dt_s, 1),
            "median_dt_s": round(self.median_dt_s, 1),
            "p90_dt_s": round(self.p90_dt_s, 1),
            "time_trouble_rate": round(self.time_trouble_rate, 3),
            "blunder_rate_insta": round(self.blunder_rate_insta, 3),
            "blunder_rate_normal": round(self.blunder_rate_normal, 3),
            "autopilot_blunders": self.autopilot_blunders,
            "calculation_failures": self.calculation_failures,
        }


@dataclass
class Summary:
    """Top-level aggregated summary."""

    username: str
    total_games: int
    total_moves: int
    acpl: float
    phase_stats: list[PhaseStats]
    time_control_stats: list[TimeControlStats]
    swing_moves: list[SwingMove]
    motifs: list[MotifBucket]
    game_summaries: list[GameSummary] = field(default_factory=list)
    time_stats: TimeStats | None = None
    opening_acpl_white: float | None = None
    opening_acpl_black: float | None = None

    def to_dict(self) -> dict:
        d = {
            "username": self.username,
            "total_games": self.total_games,
            "total_moves": self.total_moves,
            "acpl": round(self.acpl, 1),
            "phase_stats": [p.to_dict() for p in self.phase_stats],
            "time_control_stats": [t.to_dict() for t in self.time_control_stats],
            "swing_moves": [s.to_dict() for s in self.swing_moves],
            "motifs": [m.to_dict() for m in self.motifs],
            "game_summaries": [g.to_dict() for g in self.game_summaries],
        }
        if self.time_stats is not None:
            d["time_stats"] = self.time_stats.to_dict()
        if self.opening_acpl_white is not None:
            d["opening_acpl_white"] = round(self.opening_acpl_white, 1)
        if self.opening_acpl_black is not None:
            d["opening_acpl_black"] = round(self.opening_acpl_black, 1)
        return d
