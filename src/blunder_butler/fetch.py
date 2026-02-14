"""Chess.com API client with retry, backoff, and rate limiting."""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import requests

from .config import Config
from .errors import NetworkError
from .log import get_logger

BASE_URL = "https://api.chess.com/pub"
USER_AGENT = "BlunderButler/0.1 (github.com/blunder-butler)"
REQUEST_DELAY = 0.5  # seconds between requests
MAX_RETRIES = 3
BACKOFF_BASE = 2.0


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def _get_with_retry(session: requests.Session, url: str) -> dict | list:
    """GET with retry and exponential backoff."""
    logger = get_logger()
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(REQUEST_DELAY)
            resp = session.get(url, timeout=30)
            if resp.status_code == 404:
                raise NetworkError(f"Not found: {url}")
            if resp.status_code == 429:
                wait = BACKOFF_BASE ** (attempt + 1)
                logger.warning("Rate limited, waiting %.1fs", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                wait = BACKOFF_BASE ** (attempt + 1)
                logger.warning("Request failed (%s), retrying in %.1fs", e, wait)
                time.sleep(wait)
    raise NetworkError(f"Failed after {MAX_RETRIES} retries: {last_error}")


def fetch_archives(session: requests.Session, username: str) -> list[str]:
    """Fetch list of monthly archive URLs for a user."""
    url = f"{BASE_URL}/player/{username}/games/archives"
    data = _get_with_retry(session, url)
    return data.get("archives", [])


def _parse_archive_date(archive_url: str) -> tuple[int, int]:
    """Extract (year, month) from archive URL."""
    parts = archive_url.rstrip("/").split("/")
    return int(parts[-2]), int(parts[-1])


def _filter_archives_by_date(
    archives: list[str], since: datetime, until: datetime
) -> list[str]:
    """Filter archive URLs to those overlapping the date range."""
    filtered = []
    for url in archives:
        year, month = _parse_archive_date(url)
        # Archive covers the entire month
        archive_start = datetime(year, month, 1)
        if month == 12:
            archive_end = datetime(year + 1, 1, 1)
        else:
            archive_end = datetime(year, month + 1, 1)
        if archive_start < until and archive_end > since:
            filtered.append(url)
    return filtered


def fetch_monthly_games(session: requests.Session, archive_url: str) -> list[dict]:
    """Fetch all games from a monthly archive."""
    data = _get_with_retry(session, archive_url)
    return data.get("games", [])


def _classify_game_time_control(tc_str: str) -> str:
    """Classify time control string into category."""
    if not tc_str or tc_str == "-":
        return "unknown"
    # Daily games have format like "1/259200"
    if "/" in tc_str:
        parts = tc_str.split("/")
        base = int(parts[1]) if len(parts) > 1 else int(parts[0])
        if base >= 86400:
            return "daily"
    try:
        base = int(tc_str.split("+")[0])
    except ValueError:
        return "unknown"
    if base < 180:
        return "bullet"
    if base < 600:
        return "blitz"
    if base < 1800:
        return "rapid"
    return "daily"


def _should_include_game(game: dict, config: Config, username_lower: str) -> bool:
    """Check if a game passes the filters."""
    # Standard chess only
    rules = game.get("rules", "chess")
    if rules != "chess":
        return False
    # Rated filter
    if config.rated_only and not game.get("rated", False):
        return False
    # Time control filter
    if config.time_control != "all":
        tc = game.get("time_control", "")
        category = _classify_game_time_control(tc)
        if category != config.time_control:
            return False
    return True


def fetch_games(config: Config) -> tuple[list[dict], list[str]]:
    """Fetch and filter games from Chess.com.

    Returns (games, archive_urls).
    """
    logger = get_logger()
    session = _session()
    username = config.username.lower()

    logger.info("Fetching archives for %s", username)
    archives = fetch_archives(session, username)
    if not archives:
        raise NetworkError(f"No archives found for user '{config.username}'")

    # Date range
    now = datetime.utcnow()
    if config.since_date:
        since = datetime.strptime(config.since_date, "%Y-%m-%d")
    else:
        since = now - timedelta(days=config.since_days)
    if config.until_date:
        until = datetime.strptime(config.until_date, "%Y-%m-%d")
    else:
        until = now

    archives = _filter_archives_by_date(archives, since, until)
    logger.info("Fetching %d monthly archives", len(archives))

    all_games: list[dict] = []
    for archive_url in archives:
        if len(all_games) >= config.max_games:
            break
        monthly = fetch_monthly_games(session, archive_url)
        for game in monthly:
            if len(all_games) >= config.max_games:
                break
            if _should_include_game(game, config, username):
                all_games.append(game)

    logger.info("Fetched %d games after filtering", len(all_games))
    return all_games, archives
