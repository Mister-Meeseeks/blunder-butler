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
    """Select top N moves by centipawn loss.

    De-duplicates by (game_id, phase) so that repeated blunders in the same
    game phase don't dominate the list. Only the worst move per game+phase is
    kept. Moves from different phases of the same game are both included.
    """
    game_urls = {g.game_id: g.url for g in games}
    player_moves = [a for a in analyses if a.is_player_move and a.cpl > 0]
    player_moves.sort(key=lambda a: a.cpl, reverse=True)

    seen: set[tuple[str, Phase]] = set()
    swings = []
    for a in player_moves:
        if len(swings) >= n:
            break
        key = (a.game_id, a.phase)
        if key in seen:
            continue
        seen.add(key)
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


_PIECE_VALUES = {
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
    chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0,
}


def _detect_hanging_pieces(analyses: list[MoveAnalysis]) -> MotifBucket:
    """Detect hanging pieces: high CPL where best response is a capture.

    Subtype A1 (hang_en_prise): the moved piece or another piece is left
    immediately capturable with material loss >= 3.
    """
    bucket = MotifBucket(
        name="Hanging Pieces",
        description="Moves that leave pieces undefended, allowing the opponent to win material.",
    )

    candidates: list[tuple[int, MoveAnalysis, str, float, dict]] = []
    for a in analyses:
        if not a.is_player_move or a.cpl < 200:
            continue
        if not a.best_move_uci or len(a.best_move_uci) < 4:
            continue
        try:
            board = chess.Board(a.fen_before)
            player_color = board.turn
            player_move = board.parse_san(a.move_san)
            board.push(player_move)
            best_resp = chess.Move.from_uci(a.pv[0]) if a.pv else None
            if not best_resp or not board.is_capture(best_resp):
                continue

            # Classify subtype
            captured_piece = board.piece_at(best_resp.to_square)
            cap_value = _PIECE_VALUES.get(
                captured_piece.piece_type, 0
            ) if captured_piece else 0
            capturing_piece = board.piece_at(best_resp.from_square)
            cap_by_value = _PIECE_VALUES.get(
                capturing_piece.piece_type, 0
            ) if capturing_piece else 0

            # A1: en prise — opponent captures POV piece at PV ply 1
            # with material loss >= 3
            material_loss = max(0, cap_value - cap_by_value)
            # If the captured piece is worth more, or if CPL is very high
            # and capture is non-trivial, classify as en_prise
            if cap_value >= 3 or (a.cpl >= 300 and cap_value >= 1):
                subtype = "hang_en_prise"
                confidence = 0.9
                meta = {
                    "lost_piece_type": chess.piece_name(captured_piece.piece_type) if captured_piece else "",
                    "lost_square": chess.square_name(best_resp.to_square),
                    "captured_by_piece_type": chess.piece_name(capturing_piece.piece_type) if capturing_piece else "",
                }
            else:
                subtype = ""
                confidence = 0.0
                meta = {}

            candidates.append((a.cpl, a, subtype, confidence, meta))
        except Exception:
            continue

    candidates.sort(key=lambda x: x[0], reverse=True)
    bucket.count = len(candidates)

    # Track subtype counts across all candidates
    for _, _, subtype, _, _ in candidates:
        if subtype:
            bucket.subtype_counts[subtype] = bucket.subtype_counts.get(subtype, 0) + 1

    for _, a, subtype, confidence, meta in candidates[:3]:
        bucket.examples.append(MotifExample(
            game_id=a.game_id, ply=a.ply, fen=a.fen_before,
            move_san=a.move_san, best_move_san=a.best_move_san,
            eval_swing=a.cpl, pv=a.pv,
            subtype=subtype, confidence=confidence, meta=meta,
        ))
    return bucket


def _detect_knight_fork(board: chess.Board, move: chess.Move, color: chess.Color) -> bool:
    """Check if a knight move attacks 2+ high-value targets (Q/R/K)."""
    piece = board.piece_at(move.from_square)
    if not piece or piece.piece_type != chess.KNIGHT:
        return False
    # Look at what the knight attacks from the destination square
    attacked = chess.SquareSet(chess.BB_KNIGHT_ATTACKS[move.to_square])
    high_value_targets = 0
    for sq in attacked:
        target = board.piece_at(sq)
        if target and target.color != color and target.piece_type in (
            chess.QUEEN, chess.ROOK, chess.KING
        ):
            high_value_targets += 1
    return high_value_targets >= 2


def _detect_missed_tactics(analyses: list[MoveAnalysis]) -> MotifBucket:
    """Detect missed tactics: high CPL with forcing best line.

    Subtypes:
    - B1 (missed_forcing_check): best move gives check, CPL >= 200 or forced mate.
    - B2 (missed_forcing_capture): best move is a capture winning material.
    - B4 (motif_knight_fork): best move is a knight fork hitting 2+ high-value targets.
    """
    bucket = MotifBucket(
        name="Missed Tactics",
        description="Positions where a strong tactical move was available but missed.",
    )

    candidates: list[tuple[int, MoveAnalysis, str, float, dict]] = []
    for a in analyses:
        if not a.is_player_move or a.cpl < 150:
            continue
        if a.eval_before.to_cp_clamped() < -100:
            continue

        subtype = ""
        confidence = 0.0
        meta: dict = {}

        try:
            board = chess.Board(a.fen_before)
            player_color = board.turn
            best_move = chess.Move.from_uci(a.best_move_uci) if a.best_move_uci else None

            if best_move:
                is_check = board.gives_check(best_move)
                is_capture = board.is_capture(best_move)
                has_mate = (a.eval_best.is_mate and a.eval_best.mate is not None
                            and a.eval_best.mate > 0)

                # B4: knight fork (check before B1/B2 since it's more specific)
                if _detect_knight_fork(board, best_move, player_color):
                    subtype = "motif_knight_fork"
                    confidence = 0.85
                    # Find the fork targets
                    attacked = chess.SquareSet(chess.BB_KNIGHT_ATTACKS[best_move.to_square])
                    targets = []
                    for sq in attacked:
                        target = board.piece_at(sq)
                        if target and target.color != player_color and target.piece_type in (
                            chess.QUEEN, chess.ROOK, chess.KING
                        ):
                            targets.append(chess.square_name(sq))
                    meta = {"knight_to": chess.square_name(best_move.to_square),
                            "targets": targets}

                # B1: missed forcing check
                elif is_check and (a.cpl >= 200 or has_mate):
                    subtype = "missed_forcing_check"
                    confidence = 0.85 if has_mate else 0.7
                    meta = {"check_move": a.best_move_uci}
                    if has_mate:
                        meta["mate_in_plies"] = abs(a.eval_best.mate) * 2 if a.eval_best.mate else 0

                # B2: missed forcing capture
                elif is_capture and a.cpl >= 150:
                    captured = board.piece_at(best_move.to_square)
                    cap_value = _PIECE_VALUES.get(
                        captured.piece_type, 0
                    ) if captured else 0
                    if cap_value >= 1:
                        subtype = "missed_forcing_capture"
                        confidence = 0.8 if cap_value >= 3 else 0.65
                        meta = {
                            "capture_square": chess.square_name(best_move.to_square),
                            "captured_piece_type": chess.piece_name(captured.piece_type) if captured else "",
                        }
        except Exception:
            pass

        candidates.append((a.cpl, a, subtype, confidence, meta))

    candidates.sort(key=lambda x: x[0], reverse=True)
    bucket.count = len(candidates)

    for _, _, subtype, _, _ in candidates:
        if subtype:
            bucket.subtype_counts[subtype] = bucket.subtype_counts.get(subtype, 0) + 1

    for _, a, subtype, confidence, meta in candidates[:3]:
        bucket.examples.append(MotifExample(
            game_id=a.game_id, ply=a.ply, fen=a.fen_before,
            move_san=a.move_san, best_move_san=a.best_move_san,
            eval_swing=a.cpl, pv=a.pv,
            subtype=subtype, confidence=confidence, meta=meta,
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
    """Detect moves that allow opponent forcing sequences (checks/captures).

    Subtypes:
    - C1 (allowed_forcing_check): opponent reply is a check leading to mate or big loss.
    - C2 (allowed_forcing_capture): opponent reply is a capture winning material.
    """
    bucket = MotifBucket(
        name="Ignored Threats",
        description="Moves that allow opponent forcing sequences (checks/captures).",
    )

    candidates: list[tuple[int, MoveAnalysis, str, float, dict]] = []
    for a in analyses:
        if not a.is_player_move or a.cpl < 250 or not a.pv:
            continue
        try:
            board = chess.Board(a.fen_before)
            player_move = board.parse_san(a.move_san)
            board.push(player_move)
            opp_reply = chess.Move.from_uci(a.pv[0])

            is_check = board.gives_check(opp_reply)
            is_capture = board.is_capture(opp_reply)

            if not is_check and not is_capture:
                continue

            # Classify subtype — check takes priority over capture
            if is_check:
                # C1: allowed_forcing_check
                # Higher confidence if eval_after shows mate
                has_mate = a.eval_after.is_mate and a.eval_after.mate is not None and a.eval_after.mate < 0
                confidence = 0.85 if has_mate else 0.7
                meta: dict = {"first_check_move": a.pv[0]}
                if has_mate:
                    meta["mate_in_plies"] = abs(a.eval_after.mate) * 2 if a.eval_after.mate else 0
                candidates.append((a.cpl, a, "allowed_forcing_check", confidence, meta))
            else:
                # C2: allowed_forcing_capture
                captured = board.piece_at(opp_reply.to_square)
                cap_value = _PIECE_VALUES.get(
                    captured.piece_type, 0
                ) if captured else 0
                confidence = 0.85 if cap_value >= 3 else 0.7
                meta = {
                    "captured_square": chess.square_name(opp_reply.to_square),
                    "captured_piece_type": chess.piece_name(captured.piece_type) if captured else "",
                }
                candidates.append((a.cpl, a, "allowed_forcing_capture", confidence, meta))
        except Exception:
            continue

    candidates.sort(key=lambda x: x[0], reverse=True)
    bucket.count = len(candidates)

    for _, _, subtype, _, _ in candidates:
        bucket.subtype_counts[subtype] = bucket.subtype_counts.get(subtype, 0) + 1

    for _, a, subtype, confidence, meta in candidates[:3]:
        bucket.examples.append(MotifExample(
            game_id=a.game_id, ply=a.ply, fen=a.fen_before,
            move_san=a.move_san, best_move_san=a.best_move_san,
            eval_swing=a.cpl, pv=a.pv,
            subtype=subtype, confidence=confidence, meta=meta,
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

    # Opening ACPL by color
    opening_white = [a for a in player_moves
                     if a.phase == Phase.OPENING and a.side_to_move == Color.WHITE]
    opening_black = [a for a in player_moves
                     if a.phase == Phase.OPENING and a.side_to_move == Color.BLACK]
    opening_acpl_white = (
        sum(m.cpl for m in opening_white) / len(opening_white)
        if opening_white else None
    )
    opening_acpl_black = (
        sum(m.cpl for m in opening_black) / len(opening_black)
        if opening_black else None
    )

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
        opening_acpl_white=opening_acpl_white,
        opening_acpl_black=opening_acpl_black,
    )
