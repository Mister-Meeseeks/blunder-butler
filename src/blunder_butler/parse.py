"""PGN parsing via python-chess."""

from __future__ import annotations

import hashlib
import io
import re

import chess
import chess.pgn

from .log import get_logger
from .models import Color, GameResult, ParsedGame, TimeControl


def _classify_time_control(tc_str: str) -> TimeControl:
    """Classify a time control string into a category."""
    if not tc_str or tc_str == "-":
        return TimeControl.UNKNOWN
    if "/" in tc_str:
        parts = tc_str.split("/")
        base = int(parts[1]) if len(parts) > 1 else int(parts[0])
        if base >= 86400:
            return TimeControl.DAILY
    try:
        base = int(tc_str.split("+")[0])
    except ValueError:
        return TimeControl.UNKNOWN
    if base < 180:
        return TimeControl.BULLET
    if base < 600:
        return TimeControl.BLITZ
    if base < 1800:
        return TimeControl.RAPID
    return TimeControl.DAILY


def _parse_result(result_str: str, player_color: Color) -> GameResult:
    """Parse PGN result string from player perspective."""
    if result_str == "1-0":
        return GameResult.WIN if player_color == Color.WHITE else GameResult.LOSS
    if result_str == "0-1":
        return GameResult.WIN if player_color == Color.BLACK else GameResult.LOSS
    return GameResult.DRAW


def _extract_clocks(game_node: chess.pgn.Game) -> list[float | None]:
    """Extract clock times from PGN comments."""
    clocks: list[float | None] = []
    node = game_node
    while node.variations:
        node = node.variation(0)
        comment = node.comment or ""
        match = re.search(r"\[%clk\s+(\d+):(\d+):(\d+(?:\.\d+)?)\]", comment)
        if match:
            h, m, s = match.groups()
            clocks.append(int(h) * 3600 + int(m) * 60 + float(s))
        else:
            clocks.append(None)
    return clocks


def _game_id_from_url(url: str) -> str:
    """Extract or generate a game ID."""
    if url:
        # Chess.com URLs end with /game/<id>
        parts = url.rstrip("/").split("/")
        if parts:
            return parts[-1]
    return ""


def _make_game_id(pgn_text: str, fallback: str = "") -> str:
    """Generate a deterministic game ID from PGN content."""
    if fallback:
        return fallback
    return hashlib.sha256(pgn_text.encode()).hexdigest()[:12]


def parse_game_from_api(game_data: dict, username: str) -> ParsedGame | None:
    """Parse a single game from Chess.com API JSON into a ParsedGame."""
    logger = get_logger()
    pgn_text = game_data.get("pgn", "")
    if not pgn_text:
        logger.warning("Game has no PGN, skipping")
        return None

    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
    except Exception as e:
        logger.warning("Failed to parse PGN: %s", e)
        return None

    if game is None:
        logger.warning("Empty PGN, skipping")
        return None

    headers = game.headers
    white = headers.get("White", "?")
    black = headers.get("Black", "?")
    username_lower = username.lower()

    if white.lower() == username_lower:
        player_color = Color.WHITE
    elif black.lower() == username_lower:
        player_color = Color.BLACK
    else:
        logger.warning("Username '%s' not found in game %s vs %s, skipping", username, white, black)
        return None

    url = game_data.get("url", headers.get("Link", ""))
    game_id = _make_game_id(pgn_text, _game_id_from_url(url))

    result_str = headers.get("Result", "*")
    result = _parse_result(result_str, player_color)

    tc_raw = game_data.get("time_control", headers.get("TimeControl", ""))
    tc = _classify_time_control(tc_raw)

    rated = game_data.get("rated", True)
    date = headers.get("Date", headers.get("UTCDate", ""))
    eco = headers.get("ECO", "")

    # Walk moves to collect SANs and FENs
    moves_san: list[str] = []
    fens: list[str] = []
    board = game.board()
    node = game
    while node.variations:
        node = node.variation(0)
        move = node.move
        san = board.san(move)
        board.push(move)
        moves_san.append(san)
        fens.append(board.fen())

    clocks = _extract_clocks(game)

    return ParsedGame(
        game_id=game_id,
        white=white,
        black=black,
        result=result,
        date=date,
        time_control_raw=tc_raw,
        time_control=tc,
        rated=rated,
        player_color=player_color,
        moves_san=moves_san,
        fens=fens,
        clock_times=clocks,
        url=url,
        eco=eco,
    )


def parse_games(games_data: list[dict], username: str) -> list[ParsedGame]:
    """Parse a list of Chess.com API game dicts into ParsedGames."""
    logger = get_logger()
    parsed = []
    for gd in games_data:
        try:
            game = parse_game_from_api(gd, username)
            if game:
                parsed.append(game)
        except Exception as e:
            logger.warning("Skipping corrupt game: %s", e)
    logger.info("Parsed %d/%d games successfully", len(parsed), len(games_data))
    return parsed


def games_to_pgn(games_data: list[dict]) -> str:
    """Concatenate raw PGN texts from API game dicts."""
    pgns = []
    for gd in games_data:
        pgn = gd.get("pgn", "")
        if pgn:
            pgns.append(pgn.strip())
    return "\n\n".join(pgns) + "\n"
