"""Stockfish per-move analysis with multiprocessing support."""

from __future__ import annotations

import logging
import multiprocessing
import shutil
import tempfile
from pathlib import Path

import chess
from stockfish import Stockfish, StockfishException

from .cache import load_cache, load_game_cache, make_cache_key, save_game_cache, write_cache_entry
from .config import Config
from .errors import EngineError
from .log import get_logger
from .models import Color, Eval, GameResult, MoveAnalysis, MoveFlag, ParsedGame, TimeControl


def create_engine(config: Config) -> Stockfish:
    """Create and configure a Stockfish instance."""
    path = config.engine_path
    if not path:
        path = shutil.which("stockfish") or ""
    if not path:
        raise EngineError(
            "Stockfish not found. Install it or pass --engine-path."
        )
    try:
        params = {
            "Threads": config.threads,
            "Hash": config.hash_mb,
        }
        sf = Stockfish(path=path, depth=config.depth or 14, parameters=params)
        return sf
    except (StockfishException, OSError) as e:
        raise EngineError(f"Failed to start Stockfish: {e}") from e


def _eval_from_stockfish(sf: Stockfish) -> Eval:
    """Extract evaluation from Stockfish's current position (white perspective)."""
    ev = sf.get_evaluation()
    if ev["type"] == "mate":
        return Eval(mate=ev["value"])
    return Eval(cp=ev["value"])


def normalize_eval(ev: Eval, player_color: Color) -> Eval:
    """Normalize eval so positive = good for player. Stockfish returns white perspective."""
    if player_color == Color.WHITE:
        return ev
    # Flip for black
    if ev.mate is not None:
        return Eval(mate=-ev.mate)
    return Eval(cp=-(ev.cp or 0))


def classify_move(cpl: int, config: Config) -> MoveFlag:
    """Classify a move based on centipawn loss."""
    if cpl <= 0:
        return MoveFlag.BEST
    if cpl < config.inaccuracy_threshold:
        return MoveFlag.GOOD
    if cpl < config.mistake_threshold:
        return MoveFlag.INACCURACY
    if cpl < config.blunder_threshold:
        return MoveFlag.MISTAKE
    return MoveFlag.BLUNDER


def analyze_position(sf: Stockfish, fen: str, config: Config) -> tuple[Eval, str, list[str]]:
    """Analyze a single position. Returns (eval, best_move_uci, pv)."""
    sf.set_fen_position(fen)
    if config.depth:
        sf.set_depth(config.depth)
        best_move = sf.get_best_move()
    else:
        best_move = sf.get_best_move_time(config.engine_time_ms)

    # get_evaluation() reuses the last search result — no extra engine call
    ev = _eval_from_stockfish(sf)
    pv = [best_move] if best_move else []

    return ev, best_move or "", pv


def analyze_game(
    game: ParsedGame,
    config: Config,
    cache: dict[str, MoveAnalysis],
    cache_path: Path | None = None,
) -> tuple[list[MoveAnalysis], int, int]:
    """Analyze all positions in a game. Returns (analyses, cache_hits, cache_misses)."""
    logger = get_logger()

    # Check per-game cache first
    if not config.no_game_cache:
        cached_analyses = load_game_cache(game.game_id, config)
        if cached_analyses is not None:
            return cached_analyses, 0, 0

    engine_hash = config.engine_settings_hash()
    sf = create_engine(config)
    analyses: list[MoveAnalysis] = []
    cache_hits = 0
    cache_misses = 0

    # We need FEN before each move. The starting position + FENs after each ply.
    start_fen = chess.STARTING_FEN
    fens_before = [start_fen] + game.fens[:-1]  # FEN before move i = FEN after move i-1

    board = chess.Board()

    total_plies = len(game.moves_san)
    for i, (san, fen_before) in enumerate(zip(game.moves_san, fens_before)):
        ply = i + 1
        side_to_move = Color.WHITE if (ply % 2 == 1) else Color.BLACK

        # Only analyze player's moves (unless both_sides)
        is_player_move = side_to_move == game.player_color
        if not config.both_sides and not is_player_move:
            # Still need to push the move to keep board in sync
            board.set_fen(fen_before)
            try:
                move = board.parse_san(san)
                board.push(move)
            except Exception:
                pass
            continue

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("  ply %d/%d: %s", ply, total_plies, san)

        # Check cache
        cache_key = make_cache_key(fen_before, engine_hash)
        if cache_key in cache:
            cached = cache[cache_key]
            # Update game-specific fields
            analyses.append(MoveAnalysis(
                game_id=game.game_id,
                ply=ply,
                move_san=cached.move_san if cached.game_id == game.game_id else san,
                move_uci=cached.move_uci,
                fen_before=fen_before,
                side_to_move=side_to_move,
                eval_before=cached.eval_before,
                best_move_uci=cached.best_move_uci,
                best_move_san=cached.best_move_san,
                eval_best=cached.eval_best,
                eval_after=cached.eval_after,
                cpl=cached.cpl,
                flag=cached.flag,
                pv=cached.pv,
                is_player_move=is_player_move,
                clock_time=game.clock_times[i] if i < len(game.clock_times) else None,
            ))
            cache_hits += 1
            continue

        cache_misses += 1

        try:
            board.set_fen(fen_before)
            move = board.parse_san(san)
            move_uci = move.uci()

            # Analyze position before move (get best move and eval)
            eval_before_raw, best_move_uci, pv = analyze_position(sf, fen_before, config)
            eval_before = normalize_eval(eval_before_raw, game.player_color)

            # Get eval of best move
            eval_best = normalize_eval(eval_before_raw, game.player_color)

            # Analyze position after player's actual move
            board.push(move)
            fen_after = board.fen()
            eval_after_raw, _, _ = analyze_position(sf, fen_after, config)
            eval_after = normalize_eval(eval_after_raw, game.player_color)

            # CPL = max(0, eval_best_clamped - eval_after_clamped)
            cpl = max(0, eval_best.to_cp_clamped() - eval_after.to_cp_clamped())
            flag = classify_move(cpl, config)

            # Convert best move to SAN
            best_san = ""
            if best_move_uci:
                try:
                    temp_board = chess.Board(fen_before)
                    best_move_obj = chess.Move.from_uci(best_move_uci)
                    best_san = temp_board.san(best_move_obj)
                except Exception:
                    best_san = best_move_uci

            analysis = MoveAnalysis(
                game_id=game.game_id,
                ply=ply,
                move_san=san,
                move_uci=move_uci,
                fen_before=fen_before,
                side_to_move=side_to_move,
                eval_before=eval_before,
                best_move_uci=best_move_uci,
                best_move_san=best_san,
                eval_best=eval_best,
                eval_after=eval_after,
                cpl=cpl,
                flag=flag,
                pv=pv,
                is_player_move=is_player_move,
                clock_time=game.clock_times[i] if i < len(game.clock_times) else None,
            )
            analyses.append(analysis)

            # Write to cache
            if cache_path:
                write_cache_entry(cache_path, cache_key, analysis)
                cache[cache_key] = analysis

        except Exception as e:
            logger.warning("Failed to analyze ply %d in game %s: %s", ply, game.game_id, e)
            continue

    try:
        del sf
    except Exception:
        pass

    # Save to per-game cache
    if not config.no_game_cache and analyses:
        save_game_cache(game.game_id, config, analyses)

    return analyses, cache_hits, cache_misses


# Per-worker state set by _pool_initializer
_worker_id: int = 0
_worker_cache: dict[str, MoveAnalysis] = {}
_worker_cache_path: Path | None = None


def _pool_initializer(tmp_dir: str, counter: multiprocessing.Value) -> None:
    """Assign a worker ID and set up per-worker logging and cache."""
    global _worker_id, _worker_cache, _worker_cache_path
    from .log import setup_logging
    setup_logging()

    with counter.get_lock():
        _worker_id = counter.value
        counter.value += 1

    _worker_cache_path = Path(tmp_dir) / f"cache_{_worker_id}.jsonl"
    _worker_cache = {}


def _worker_analyze_one(args: tuple) -> tuple[list[dict], int, int]:
    """Analyze a single game in a worker process."""
    game_dict, config_dict, game_index, total_games = args
    logger = get_logger()
    config = Config(**config_dict)

    game_dict["result"] = GameResult(game_dict["result"])
    game_dict["time_control"] = TimeControl(game_dict["time_control"])
    game_dict["player_color"] = Color(game_dict["player_color"])
    game = ParsedGame(**game_dict)

    logger.info("[w%d] Analyzing game %d/%d (%s, %d plies)",
                _worker_id, game_index + 1, total_games,
                game.game_id[:8], len(game.moves_san))

    analyses, hits, misses = analyze_game(
        game, config, _worker_cache, _worker_cache_path,
    )
    return [a.to_dict() for a in analyses], hits, misses


def analyze_all_games(
    games: list[ParsedGame],
    config: Config,
    cache_path: Path,
) -> tuple[list[MoveAnalysis], int, int]:
    """Analyze all games, optionally using multiprocessing."""
    logger = get_logger()

    if config.workers <= 1:
        # Single-process mode
        cache = load_cache(cache_path) if config.resume else {}
        all_analyses: list[MoveAnalysis] = []
        total_hits = 0
        total_misses = 0

        for i, game in enumerate(games):
            logger.info("Analyzing game %d/%d (%s, %d plies)", i + 1, len(games), game.game_id[:8], len(game.moves_san))
            analyses, hits, misses = analyze_game(game, config, cache, cache_path)
            all_analyses.extend(analyses)
            total_hits += hits
            total_misses += misses

        logger.info(
            "Analysis complete: %d positions, %d cache hits, %d cache misses",
            len(all_analyses), total_hits, total_misses,
        )
        return all_analyses, total_hits, total_misses

    # Multi-process mode
    logger.info("Using %d workers for analysis", config.workers)

    game_dicts = []
    for g in games:
        game_dicts.append({
            "game_id": g.game_id, "white": g.white, "black": g.black,
            "result": g.result.value, "date": g.date,
            "time_control_raw": g.time_control_raw,
            "time_control": g.time_control.value, "rated": g.rated,
            "player_color": g.player_color.value,
            "moves_san": g.moves_san, "fens": g.fens,
            "clock_times": g.clock_times, "url": g.url, "eco": g.eco,
        })

    config_dict = {
        "username": config.username, "engine_time_ms": config.engine_time_ms,
        "depth": config.depth, "threads": config.threads, "hash_mb": config.hash_mb,
        "engine_path": config.engine_path, "both_sides": config.both_sides,
        "inaccuracy_threshold": config.inaccuracy_threshold,
        "mistake_threshold": config.mistake_threshold,
        "blunder_threshold": config.blunder_threshold,
        "output_dir": config.output_dir,
        "no_game_cache": config.no_game_cache,
        "workers": 1,  # each worker is single-threaded
    }

    tmp_dir = tempfile.mkdtemp(prefix="blunder_butler_")
    counter = multiprocessing.Value("i", 0)

    # One work item per game — workers pull from a common pool
    total = len(game_dicts)
    worker_args = [
        (gd, config_dict, i, total) for i, gd in enumerate(game_dicts)
    ]

    all_analyses = []
    total_hits = 0
    total_misses = 0
    completed = 0

    with multiprocessing.Pool(
        config.workers,
        initializer=_pool_initializer,
        initargs=(tmp_dir, counter),
    ) as pool:
        for analyses_dicts, hits, misses in pool.imap_unordered(
            _worker_analyze_one, worker_args,
        ):
            for ad in analyses_dicts:
                all_analyses.append(MoveAnalysis.from_dict(ad))
            total_hits += hits
            total_misses += misses
            completed += 1
            logger.info("Progress: %d/%d games complete", completed, total)

    logger.info(
        "Analysis complete: %d positions, %d cache hits, %d cache misses",
        len(all_analyses), total_hits, total_misses,
    )
    return all_analyses, total_hits, total_misses
