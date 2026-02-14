"""Stockfish per-move analysis with multiprocessing support."""

from __future__ import annotations

import multiprocessing
import shutil
import tempfile
from pathlib import Path

import chess
from stockfish import Stockfish, StockfishException

from .cache import load_cache, make_cache_key, write_cache_entry
from .config import Config
from .errors import EngineError
from .log import get_logger
from .models import Color, Eval, MoveAnalysis, MoveFlag, ParsedGame


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
    else:
        # Use time-based analysis
        sf.set_depth(20)  # max depth, will be limited by time

    # Get best move and PV
    best_move = sf.get_best_move_time(config.engine_time_ms) if not config.depth else sf.get_best_move()
    ev = _eval_from_stockfish(sf)

    # Get PV (top line)
    top_moves = sf.get_top_moves(1)
    pv = []
    if top_moves:
        line = top_moves[0].get("Move", "")
        pv = [line] if line else []
        # Some versions return full PV
        if "Centipawn" in top_moves[0] or "Mate" in top_moves[0]:
            pass  # eval already captured

    return ev, best_move or "", pv


def analyze_game(
    game: ParsedGame,
    config: Config,
    cache: dict[str, MoveAnalysis],
    cache_path: Path | None = None,
) -> tuple[list[MoveAnalysis], int, int]:
    """Analyze all positions in a game. Returns (analyses, cache_hits, cache_misses)."""
    logger = get_logger()
    engine_hash = config.engine_settings_hash()
    sf = create_engine(config)
    analyses: list[MoveAnalysis] = []
    cache_hits = 0
    cache_misses = 0

    # We need FEN before each move. The starting position + FENs after each ply.
    start_fen = chess.STARTING_FEN
    fens_before = [start_fen] + game.fens[:-1]  # FEN before move i = FEN after move i-1

    board = chess.Board()

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

            # Now get eval after player's actual move
            board.push(move)
            fen_after = board.fen()
            sf.set_fen_position(fen_after)
            if config.depth:
                sf.set_depth(config.depth)
            eval_after_raw = _eval_from_stockfish(sf)
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

    return analyses, cache_hits, cache_misses


def _worker_analyze(args: tuple) -> tuple[list[dict], int, int]:
    """Worker function for multiprocessing. Analyzes a batch of games."""
    from .log import setup_logging
    setup_logging()

    games_data, config_dict, cache_path_str = args
    config = Config(**config_dict)
    cache_path = Path(cache_path_str) if cache_path_str else None

    # Load cache for this worker
    cache: dict[str, MoveAnalysis] = {}
    if cache_path and cache_path.exists():
        cache = load_cache(cache_path)

    all_analyses: list[dict] = []
    total_hits = 0
    total_misses = 0

    for game_dict in games_data:
        game = ParsedGame(**game_dict)
        analyses, hits, misses = analyze_game(game, config, cache, cache_path)
        all_analyses.extend(a.to_dict() for a in analyses)
        total_hits += hits
        total_misses += misses

    return all_analyses, total_hits, total_misses


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
            if (i + 1) % 10 == 0 or i == 0:
                logger.info("Analyzing game %d/%d", i + 1, len(games))
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

    # Distribute games across workers
    chunks: list[list[dict]] = [[] for _ in range(config.workers)]
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

    for i, gd in enumerate(game_dicts):
        chunks[i % config.workers].append(gd)

    # Create per-worker temp cache files
    config_dict = {
        "username": config.username, "engine_time_ms": config.engine_time_ms,
        "depth": config.depth, "threads": config.threads, "hash_mb": config.hash_mb,
        "engine_path": config.engine_path, "both_sides": config.both_sides,
        "inaccuracy_threshold": config.inaccuracy_threshold,
        "mistake_threshold": config.mistake_threshold,
        "blunder_threshold": config.blunder_threshold,
        "workers": 1,  # each worker is single-threaded
    }

    tmp_dir = tempfile.mkdtemp(prefix="blunder_butler_")
    worker_args = []
    for i, chunk in enumerate(chunks):
        if not chunk:
            continue
        tmp_cache = str(Path(tmp_dir) / f"cache_{i}.jsonl")
        worker_args.append((chunk, config_dict, tmp_cache))

    with multiprocessing.Pool(config.workers) as pool:
        results = pool.map(_worker_analyze, worker_args)

    # Merge results
    all_analyses = []
    total_hits = 0
    total_misses = 0
    for analyses_dicts, hits, misses in results:
        for ad in analyses_dicts:
            all_analyses.append(MoveAnalysis.from_dict(ad))
        total_hits += hits
        total_misses += misses

    logger.info(
        "Analysis complete: %d positions, %d cache hits, %d cache misses",
        len(all_analyses), total_hits, total_misses,
    )
    return all_analyses, total_hits, total_misses
