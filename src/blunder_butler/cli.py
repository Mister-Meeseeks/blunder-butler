"""CLI entry point using Click."""

from __future__ import annotations

import sys

import click

from .config import Config
from .errors import BlunderButlerError
from .log import setup_logging
from .pipeline import run_pipeline


@click.command()
@click.argument("username")
@click.option("--time-control", default="all", type=click.Choice(
    ["bullet", "blitz", "rapid", "daily", "all"], case_sensitive=False),
    help="Filter by time control category.")
@click.option("--since", "since_days", default=90, type=int,
    help="Fetch games from the last N days.")
@click.option("--since-date", default="", help="Fetch games since YYYY-MM-DD (overrides --since).")
@click.option("--until-date", default="", help="Fetch games until YYYY-MM-DD.")
@click.option("--max-games", default=100, type=int, help="Maximum number of games to fetch.")
@click.option("--rated-only/--include-unrated", default=True, help="Only analyze rated games.")
@click.option("--engine-time-ms", default=100, type=int,
    help="Stockfish analysis time per move in milliseconds.")
@click.option("--depth", default=None, type=int,
    help="Stockfish analysis depth (mutually exclusive with --engine-time-ms).")
@click.option("--engine-path", default="", help="Path to Stockfish binary.")
@click.option("--threads", default=1, type=int, help="Stockfish threads per engine instance.")
@click.option("--hash-mb", default=64, type=int, help="Stockfish hash table size in MB.")
@click.option("--workers", default=4, type=int,
    help="Number of parallel analysis workers (each gets its own engine).")
@click.option("--both-sides", is_flag=True, default=False,
    help="Analyze both players' moves (not just the target user).")
@click.option("--llm", default="off", type=click.Choice(["on", "off"], case_sensitive=False),
    help="Enable LLM-powered report narrative.")
@click.option("--llm-endpoint", default="", envvar="LLM_ENDPOINT",
    help="OpenAI-compatible API endpoint.")
@click.option("--llm-model", default="", envvar="LLM_MODEL", help="LLM model name.")
@click.option("--llm-api-key", default="", envvar="LLM_API_KEY", help="LLM API key.")
@click.option("--resume", is_flag=True, default=False,
    help="Resume analysis using cached positions.")
@click.option("--fetch-cache-ttl", default=300, type=int,
    help="Fetch cache TTL in seconds (default 300).")
@click.option("--no-fetch-cache", is_flag=True, default=False,
    help="Bypass fetch cache (still writes cache for future runs).")
@click.option("--output-dir", default="out", help="Output directory.")
@click.option("--openings-only", is_flag=True, default=False,
    help="Only report on opening phase (debugging).")
@click.option("--endgames-only", is_flag=True, default=False,
    help="Only report on endgame phase (debugging).")
@click.option("--verbose", is_flag=True, default=False, help="Enable debug logging.")
@click.option("--inaccuracy-threshold", default=50, type=int,
    help="CPL threshold for inaccuracy classification.")
@click.option("--mistake-threshold", default=100, type=int,
    help="CPL threshold for mistake classification.")
@click.option("--blunder-threshold", default=200, type=int,
    help="CPL threshold for blunder classification.")
def main(
    username: str,
    time_control: str,
    since_days: int,
    since_date: str,
    until_date: str,
    max_games: int,
    rated_only: bool,
    engine_time_ms: int,
    depth: int | None,
    engine_path: str,
    threads: int,
    hash_mb: int,
    workers: int,
    both_sides: bool,
    llm: str,
    llm_endpoint: str,
    llm_model: str,
    llm_api_key: str,
    resume: bool,
    fetch_cache_ttl: int,
    no_fetch_cache: bool,
    output_dir: str,
    openings_only: bool,
    endgames_only: bool,
    verbose: bool,
    inaccuracy_threshold: int,
    mistake_threshold: int,
    blunder_threshold: int,
) -> None:
    """Analyze Chess.com games for USERNAME and generate a coaching report."""
    setup_logging(verbose)

    config = Config(
        username=username,
        time_control=time_control.lower(),
        since_days=since_days,
        since_date=since_date,
        until_date=until_date,
        max_games=max_games,
        rated_only=rated_only,
        engine_time_ms=engine_time_ms,
        depth=depth,
        engine_path=engine_path,
        threads=threads,
        hash_mb=hash_mb,
        workers=workers,
        both_sides=both_sides,
        llm=llm.lower(),
        llm_endpoint=llm_endpoint,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        resume=resume,
        fetch_cache_ttl=fetch_cache_ttl,
        no_fetch_cache=no_fetch_cache,
        output_dir=output_dir,
        openings_only=openings_only,
        endgames_only=endgames_only,
        inaccuracy_threshold=inaccuracy_threshold,
        mistake_threshold=mistake_threshold,
        blunder_threshold=blunder_threshold,
    )

    try:
        run_dir = run_pipeline(config)
        click.echo(f"Report written to: {run_dir / 'report' / 'report.md'}")
    except BlunderButlerError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        click.echo("\nAborted.", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        sys.exit(5)


if __name__ == "__main__":
    main()
