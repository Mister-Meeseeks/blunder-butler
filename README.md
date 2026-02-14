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

### Common options

```bash
blunder-butler hikaru --time-control blitz --max-games 50 --engine-time-ms 500
```

Run `blunder-butler --help` for all options.
