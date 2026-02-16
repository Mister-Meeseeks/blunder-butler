# Blunder Butler

Chess.com game analysis and coaching report generator. Fetches your games, runs Stockfish analysis, detects weaknesses by game phase, and produces a Markdown coaching report.

## Quickstart

### Prerequisites

**Stockfish** must be installed and available on your PATH:

```bash
# macOS
brew install stockfish

# Ubuntu/Debian
sudo apt install stockfish

# Or download from https://stockfishchess.org/download/
```

### Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Run

```bash
blunder-butler <your-chess.com-username>
```

This fetches your last 90 days of rated games, analyzes them with Stockfish, and writes a report to `out/<username>/<run_id>/report/report.md`.

### Single-game analysis

Analyze a single game with historical context from your most recent bulk run:

```bash
blunder-butler USERNAME --game latest          # Latest game (always fetches fresh from API)
blunder-butler USERNAME --game -3              # 3 games ago
blunder-butler USERNAME --game 144991567688    # By game ID
blunder-butler USERNAME --game https://www.chess.com/game/live/144991567688  # By URL
```

The `latest` and offset selectors always fetch fresh games from Chess.com, so you can run this immediately after finishing a game. Game ID and URL selectors check the local cache first.

Output is written to `out/<username>/single_<game_id>_<timestamp>/`. If a previous bulk run exists, the report includes a comparison to your historical baseline.

Combine with `--llm on` for an LLM-powered coaching narrative. When a previous bulk LLM report exists, the single-game report is framed as a follow-up from the same coach:

```bash
blunder-butler USERNAME --game latest --llm on
```

### Output files

Both bulk and single-game modes always produce:
- `report.md` — the primary report (LLM narrative when `--llm on`, deterministic otherwise)
- `summary.md` — deterministic stats report (always generated alongside the LLM report)
- `summary.json` / `evidence.json` — structured data

### Common options

```bash
blunder-butler hikaru --time-control blitz --max-games 50 --engine-time-ms 500
```

Run `blunder-butler --help` for all options.
