"""Aggregation: ACPL stats, motif heuristics, swing move selection."""

from __future__ import annotations

from collections import defaultdict

import chess

from .models import (
    Color,
    GameResult,
    GameSummary,
    MotifBucket,
    MotifExample,
    MoveAnalysis,
    MoveFlag,
    ParsedGame,
    Phase,
    PhaseStats,
    Summary,
    SwingMove,
    TimeControl,
    TimeControlStats,
)
from .time_analysis import compute_time_stats


def _compute_phase_stats(analyses: list[MoveAnalysis]) -> list[PhaseStats]:
    """Compute per-phase statistics."""
    by_phase: dict[Phase, list[MoveAnalysis]] = defaultdict(list)
    for a in analyses:
        if a.is_player_move:
            by_phase[a.phase].append(a)

    stats = []
    for phase in Phase:
        moves = by_phase.get(phase, [])
        n = len(moves)
        if n == 0:
            stats.append(PhaseStats(phase=phase))
            continue

        total_cpl = sum(m.cpl for m in moves)
        blunders = sum(1 for m in moves if m.flag == MoveFlag.BLUNDER)
        mistakes = sum(1 for m in moves if m.flag == MoveFlag.MISTAKE)
        inaccuracies = sum(1 for m in moves if m.flag == MoveFlag.INACCURACY)

        stats.append(PhaseStats(
            phase=phase,
            total_moves=n,
            acpl=total_cpl / n,
            blunders=blunders,
            mistakes=mistakes,
            inaccuracies=inaccuracies,
            blunders_per_100=blunders * 100 / n,
            mistakes_per_100=mistakes * 100 / n,
            inaccuracies_per_100=inaccuracies * 100 / n,
        ))

    return stats


def _compute_time_control_stats(
    analyses: list[MoveAnalysis], games: list[ParsedGame]
) -> list[TimeControlStats]:
    """Compute per-time-control statistics."""
    game_tc: dict[str, TimeControl] = {g.game_id: g.time_control for g in games}

    by_tc: dict[TimeControl, list[MoveAnalysis]] = defaultdict(list)
    games_per_tc: dict[TimeControl, set[str]] = defaultdict(set)

    for a in analyses:
        if not a.is_player_move:
            continue
        tc = game_tc.get(a.game_id, TimeControl.UNKNOWN)
        by_tc[tc].append(a)
        games_per_tc[tc].add(a.game_id)

    stats = []
    for tc in TimeControl:
        moves = by_tc.get(tc, [])
        n = len(moves)
        if n == 0:
            continue
        total_cpl = sum(m.cpl for m in moves)
        blunders = sum(1 for m in moves if m.flag == MoveFlag.BLUNDER)
        mistakes = sum(1 for m in moves if m.flag == MoveFlag.MISTAKE)

        stats.append(TimeControlStats(
            time_control=tc,
            games=len(games_per_tc[tc]),
            total_moves=n,
            acpl=total_cpl / n,
            blunders_per_100=blunders * 100 / n,
            mistakes_per_100=mistakes * 100 / n,
        ))

    return stats


def _top_swing_moves(
    analyses: list[MoveAnalysis], games: list[ParsedGame], n: int = 10
) -> list[SwingMove]:
    """Select top N moves by centipawn loss."""
    game_urls = {g.game_id: g.url for g in games}
    player_moves = [a for a in analyses if a.is_player_move and a.cpl > 0]
    player_moves.sort(key=lambda a: a.cpl, reverse=True)

    swings = []
    for a in player_moves[:n]:
        swings.append(SwingMove(
            game_id=a.game_id,
            ply=a.ply,
            move_san=a.move_san,
            fen_before=a.fen_before,
            best_move_san=a.best_move_san,
            cpl=a.cpl,
            eval_before=a.eval_before,
            eval_after=a.eval_after,
            pv=a.pv,
            phase=a.phase,
            game_url=game_urls.get(a.game_id, ""),
        ))
    return swings


def _detect_hanging_pieces(analyses: list[MoveAnalysis]) -> MotifBucket:
    """Detect hanging pieces: high CPL where best response is a capture."""
    bucket = MotifBucket(
        name="Hanging Pieces",
        description="Moves that leave pieces undefended, allowing the opponent to win material.",
    )

    candidates = []
    for a in analyses:
        if not a.is_player_move or a.cpl < 200:
            continue
        # Check if the best move (what opponent should play) involves a capture
        # We approximate by checking if best_move targets a square with a piece
        if not a.best_move_uci or len(a.best_move_uci) < 4:
            continue
        try:
            board = chess.Board(a.fen_before)
            player_move = board.parse_san(a.move_san)
            board.push(player_move)
            # Check if opponent's best response is a capture
            best_resp = chess.Move.from_uci(a.pv[0]) if a.pv else None
            if best_resp and board.is_capture(best_resp):
                candidates.append((a.cpl, a))
        except Exception:
            continue

    candidates.sort(key=lambda x: x[0], reverse=True)
    bucket.count = len(candidates)
    for _, a in candidates[:3]:
        bucket.examples.append(MotifExample(
            game_id=a.game_id, ply=a.ply, fen=a.fen_before,
            move_san=a.move_san, best_move_san=a.best_move_san,
            eval_swing=a.cpl, pv=a.pv,
        ))
    return bucket


def _detect_missed_tactics(analyses: list[MoveAnalysis]) -> MotifBucket:
    """Detect missed tactics: high CPL with forcing best line."""
    bucket = MotifBucket(
        name="Missed Tactics",
        description="Positions where a strong tactical move was available but missed.",
    )

    candidates = []
    for a in analyses:
        if not a.is_player_move or a.cpl < 150:
            continue
        # High CPL suggests a better move existed
        # We consider it a missed tactic if the position was roughly equal or better before
        if a.eval_before.to_cp_clamped() >= -100:
            candidates.append((a.cpl, a))

    candidates.sort(key=lambda x: x[0], reverse=True)
    bucket.count = len(candidates)
    for _, a in candidates[:3]:
        bucket.examples.append(MotifExample(
            game_id=a.game_id, ply=a.ply, fen=a.fen_before,
            move_san=a.move_san, best_move_san=a.best_move_san,
            eval_swing=a.cpl, pv=a.pv,
        ))
    return bucket


def _detect_king_safety(analyses: list[MoveAnalysis]) -> MotifBucket:
    """Detect king safety issues: blunders in middlegame with king exposure."""
    bucket = MotifBucket(
        name="King Safety",
        description="Blunders correlated with weakened king position or pawn shield.",
    )

    candidates = []
    for a in analyses:
        if not a.is_player_move or a.phase != Phase.MIDDLEGAME or a.cpl < 200:
            continue
        try:
            board = chess.Board(a.fen_before)
            color = chess.WHITE if a.side_to_move == Color.WHITE else chess.BLACK
            king_sq = board.king(color)
            if king_sq is None:
                continue
            # Check if king is castled (on g/h or a/b file) and pawn shield is weakened
            king_file = chess.square_file(king_sq)
            king_rank = chess.square_rank(king_sq)
            # Rough heuristic: king is on back rank-ish and pawns in front are missing
            if (color == chess.WHITE and king_rank <= 1) or (color == chess.BLACK and king_rank >= 6):
                # Count pawns in front of king
                shield_files = [max(0, king_file - 1), king_file, min(7, king_file + 1)]
                shield_rank = king_rank + 1 if color == chess.WHITE else king_rank - 1
                pawns = 0
                for f in shield_files:
                    sq = chess.square(f, shield_rank)
                    piece = board.piece_at(sq)
                    if piece and piece.piece_type == chess.PAWN and piece.color == color:
                        pawns += 1
                if pawns < 2:  # weakened shield
                    candidates.append((a.cpl, a))
        except Exception:
            continue

    candidates.sort(key=lambda x: x[0], reverse=True)
    bucket.count = len(candidates)
    for _, a in candidates[:3]:
        bucket.examples.append(MotifExample(
            game_id=a.game_id, ply=a.ply, fen=a.fen_before,
            move_san=a.move_san, best_move_san=a.best_move_san,
            eval_swing=a.cpl, pv=a.pv,
        ))
    return bucket


def _detect_endgame_technique(analyses: list[MoveAnalysis]) -> MotifBucket:
    """Detect endgame technique issues: high ACPL with low blunder rate."""
    bucket = MotifBucket(
        name="Endgame Technique",
        description="Consistent small inaccuracies in endgames suggesting technique gaps.",
    )

    endgame_moves = [a for a in analyses if a.is_player_move and a.phase == Phase.ENDGAME]
    if not endgame_moves:
        return bucket

    total_cpl = sum(m.cpl for m in endgame_moves)
    n = len(endgame_moves)
    acpl = total_cpl / n if n > 0 else 0
    blunder_rate = sum(1 for m in endgame_moves if m.flag == MoveFlag.BLUNDER) / n if n > 0 else 0

    # High ACPL but low blunder rate = technique issue (many small leaks)
    if acpl > 30 and blunder_rate < 0.1:
        inaccurate_moves = [(m.cpl, m) for m in endgame_moves if m.cpl > 20]
        inaccurate_moves.sort(key=lambda x: x[0], reverse=True)
        bucket.count = len(inaccurate_moves)
        for _, a in inaccurate_moves[:3]:
            bucket.examples.append(MotifExample(
                game_id=a.game_id, ply=a.ply, fen=a.fen_before,
                move_san=a.move_san, best_move_san=a.best_move_san,
                eval_swing=a.cpl, pv=a.pv,
            ))

    return bucket


def _detect_ignored_threats(analyses: list[MoveAnalysis]) -> MotifBucket:
    """Detect moves that allow opponent forcing sequences (checks/captures)."""
    bucket = MotifBucket(
        name="Ignored Threats",
        description="Moves that allow opponent forcing sequences (checks/captures).",
    )

    candidates = []
    for a in analyses:
        if not a.is_player_move or a.cpl < 250 or not a.pv:
            continue
        try:
            board = chess.Board(a.fen_before)
            player_move = board.parse_san(a.move_san)
            board.push(player_move)
            # Check if opponent's best reply is a check or capture
            opp_reply = chess.Move.from_uci(a.pv[0])
            if board.gives_check(opp_reply) or board.is_capture(opp_reply):
                candidates.append((a.cpl, a))
        except Exception:
            continue

    candidates.sort(key=lambda x: x[0], reverse=True)
    bucket.count = len(candidates)
    for _, a in candidates[:3]:
        bucket.examples.append(MotifExample(
            game_id=a.game_id, ply=a.ply, fen=a.fen_before,
            move_san=a.move_san, best_move_san=a.best_move_san,
            eval_swing=a.cpl, pv=a.pv,
        ))
    return bucket


def _detect_material_givebacks(analyses: list[MoveAnalysis]) -> MotifBucket:
    """Detect winning material then immediately giving it back."""
    bucket = MotifBucket(
        name="Material Givebacks",
        description="Winning material then immediately giving it back.",
    )

    by_game: dict[str, list[MoveAnalysis]] = defaultdict(list)
    for a in analyses:
        if a.is_player_move:
            by_game[a.game_id].append(a)

    candidates = []
    for game_id, moves in by_game.items():
        moves.sort(key=lambda m: m.ply)
        for i in range(len(moves)):
            current = moves[i]
            # Check for eval spike (material win): eval jumped by >= 200cp
            spike = current.eval_after.to_cp_clamped() - current.eval_before.to_cp_clamped()
            if spike < 200:
                continue
            # Look ahead 1-3 player moves for drawdown
            for j in range(i + 1, min(i + 4, len(moves))):
                next_move = moves[j]
                drop = current.eval_after.to_cp_clamped() - next_move.eval_after.to_cp_clamped()
                if drop >= 250:
                    candidates.append((drop, next_move))
                    break

    candidates.sort(key=lambda x: x[0], reverse=True)
    bucket.count = len(candidates)
    for _, a in candidates[:3]:
        bucket.examples.append(MotifExample(
            game_id=a.game_id, ply=a.ply, fen=a.fen_before,
            move_san=a.move_san, best_move_san=a.best_move_san,
            eval_swing=a.cpl, pv=a.pv,
        ))
    return bucket


def compute_game_summaries(
    analyses: list[MoveAnalysis], games: list[ParsedGame]
) -> list[GameSummary]:
    """Compute per-game summary stats."""
    by_game: dict[str, list[MoveAnalysis]] = defaultdict(list)
    for a in analyses:
        if a.is_player_move:
            by_game[a.game_id].append(a)

    game_info = {g.game_id: g for g in games}
    summaries = []

    for game_id, moves in by_game.items():
        g = game_info.get(game_id)
        if not g:
            continue
        n = len(moves)
        total_cpl = sum(m.cpl for m in moves)
        summaries.append(GameSummary(
            game_id=game_id,
            player_color=g.player_color,
            result=g.result,
            time_control=g.time_control,
            opponent=g.opponent_name,
            total_moves=n,
            acpl=total_cpl / n if n > 0 else 0,
            blunders=sum(1 for m in moves if m.flag == MoveFlag.BLUNDER),
            mistakes=sum(1 for m in moves if m.flag == MoveFlag.MISTAKE),
            inaccuracies=sum(1 for m in moves if m.flag == MoveFlag.INACCURACY),
            url=g.url,
            date=g.date,
        ))

    return summaries


def compute_summary(
    analyses: list[MoveAnalysis], games: list[ParsedGame], username: str
) -> Summary:
    """Compute the full aggregated summary."""
    player_moves = [a for a in analyses if a.is_player_move]
    total_cpl = sum(m.cpl for m in player_moves)
    n = len(player_moves)

    phase_stats = _compute_phase_stats(analyses)
    tc_stats = _compute_time_control_stats(analyses, games)
    swing_moves = _top_swing_moves(analyses, games)
    game_summaries = compute_game_summaries(analyses, games)

    # Motif detection
    motifs = []
    for detector in [
        _detect_hanging_pieces,
        _detect_missed_tactics,
        _detect_ignored_threats,
        _detect_king_safety,
        _detect_endgame_technique,
        _detect_material_givebacks,
    ]:
        bucket = detector(analyses)
        if bucket.count > 0:
            motifs.append(bucket)

    # Time management analytics
    time_stats = compute_time_stats(analyses, games)

    return Summary(
        username=username,
        total_games=len(games),
        total_moves=n,
        acpl=total_cpl / n if n > 0 else 0,
        phase_stats=phase_stats,
        time_control_stats=tc_stats,
        swing_moves=swing_moves,
        motifs=motifs,
        game_summaries=game_summaries,
        time_stats=time_stats,
    )
