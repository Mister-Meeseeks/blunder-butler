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
blunder-butler USERNAME --game latest          # Latest game
blunder-butler USERNAME --game -3              # 3 games ago
blunder-butler USERNAME --game 144991567688    # By game ID
blunder-butler USERNAME --game https://www.chess.com/game/live/144991567688  # By URL
```

Output is written to `out/<username>/single_<game_id>_<timestamp>/report.md`. If a previous bulk run exists, the report includes a comparison to your historical baseline.

Combine with `--llm on` for an LLM-powered coaching narrative:

```bash
blunder-butler USERNAME --game latest --llm on
```

### Common options

```bash
blunder-butler hikaru --time-control blitz --max-games 50 --engine-time-ms 500
```

Run `blunder-butler --help` for all options.
