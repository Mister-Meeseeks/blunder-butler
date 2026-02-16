# agents.md

This repo is a local-first “one button” chess coaching pipeline:

**Chess.com PGN export (by username) → Stockfish analysis → aggregated weaknesses → LLM-written report.**

It is designed for reasonably technical users:
- clone repo
- install deps
- run one command with a Chess.com username
- get a report (Markdown + JSON artifacts) with sensible defaults
- optional CLI knobs to tune time controls, sampling, engine budget, etc.

---

## Product goals

### Primary user story
> “I want to enter my Chess.com username and get a high-level diagnosis of my weak points (opening vs middlegame vs endgame, common mistake types), supported by concrete examples and a simple training plan.”

### UX principles
- **One command** produces something useful.
- Defaults should be **fast, correct, and explainable**.
- Runs **fully locally** (no required web app).
- Output artifacts are deterministic and easy to inspect:
  - raw games (PGN)
  - analysis cache (JSON/SQLite)
  - aggregated stats (JSON)
  - report (Markdown)

### Non-goals (v1)
- No live in-game coaching.
- No engine cloud services.
- No opening book repertoire building.
- No perfect “motif classification” — heuristics are fine if grounded.

---

## Supported inputs

### Source
- Chess.com via the public “Published Data API”:
  - game archives (list of months)
  - monthly PGN or monthly JSON (each game includes PGN)

### Game filters (v1)
- Time control:
  - bullet / blitz / rapid / daily / all
- Date range:
  - last N days, or explicit `--since` / `--until`
- Game type:
  - rated only (default)
  - optionally include unrated

### Reasonable defaults
- `--time-control all`
- `--rated-only true`
- `--since 90d` (last 90 days)
- `--max-games 300` (cap for speed)
- exclude variants (only standard chess)

---

## Outputs

### Bulk run

All outputs live under `./out/<username>/<run_id>/`:

- `raw/archives.json` — months available
- `raw/games.pgn` — the fetched PGN set (concatenated)
- `analysis/moves.jsonl` — per-move analysis records (append-only)
- `analysis/games.jsonl` — per-game summary (result, time control, etc.)
- `stats/summary.json` — aggregated weakness metrics
- `report/report.md` — primary report (LLM narrative when enabled, deterministic otherwise)
- `report/summary.md` — deterministic stats report (always generated)
- `report/evidence.json` — LLM evidence packet

### Single-game run

Outputs live under `./out/<username>/single_<game_id>_<timestamp>/`:

- `report.md` — primary report (LLM narrative when enabled, deterministic otherwise)
- `summary.md` — deterministic stats report (always generated)
- `summary.json` — structured game stats
- `evidence.json` — LLM evidence packet

The report must be understandable even without the JSON.

---

## Pipeline stages

### 1) Fetch
**Input:** Chess.com username + filters  
**Output:** concatenated PGN, plus metadata

Rules:
- Be polite to the API: rate limit requests and retry with backoff.
- Save raw responses where helpful for debugging.
- Avoid re-downloading if identical inputs were already fetched (cache key).

### 2) Parse
**Input:** PGN  
**Output:** normalized game list with:
- game id (derived)
- headers (date, time control, rated, color, result)
- move list
- optional clock times (if present)

Implementation notes:
- Use `python-chess` PGN parser.
- Validate legality by trusting PGN; skip corrupt games with warnings.

### 3) Analyze with Stockfish
**Input:** per-move positions (FEN)  
**Output:** per-move records, stored as JSONL or SQLite

Engine budget defaults (fast MVP):
- `--engine-time-ms 200` per move (or depth 12–14)
- `--multipv 1` by default
- analyze:
  - all user moves
  - optionally both sides (`--both-sides`)

Per-move record schema (v1):
- game_id, ply, move_uci, san
- fen_before
- side_to_move
- eval_before (cp or mate)
- best_move_uci
- eval_best
- eval_after_user_move
- centipawn_loss (CPL) = eval_best - eval_after_user_move (normalized from player perspective)
- pv (principal variation) short (e.g., 6–10 plies)
- flags:
  - inaccuracy/mistake/blunder thresholds (configurable)

Important:
- Normalize evals so “positive = good for the player we’re evaluating.”
- Treat mates separately (mate distance).
- Cache analysis by `fen_before + engine_settings_hash` to avoid recompute.

### 4) Phase detection
We need opening/middlegame/endgame buckets for aggregation.

Default heuristics (good enough):
- Opening: plies 1–20 OR until both sides have moved at least 2 minors (roughly developed).
- Endgame: “phase score” below threshold (material low), e.g. no queens or total non-pawn material < X.
- Middlegame: everything else.

We store the phase label per move.

### 5) Aggregation & motif heuristics
We aggregate into actionable metrics.

Must-have aggregates:
- ACPL overall + by phase
- blunders/mistakes/inaccuracies per 100 moves (overall + by phase)
- “swing” moves: top N by CPL (worst moves)
- time-control breakdowns (separate stats per category)

Motif-ish heuristics (v1):
These are heuristic labels, not guaranteed truth. They must be grounded in engine outcomes.

Examples:
- **Hang**: after user move, best line wins a piece immediately (material delta detectable from engine PV or static exchange).
- **Missed tactic**: best move yields big eval jump but user move doesn’t; label only if CPL > threshold and PV shows forced material/mate.
- **King safety**: CPL correlates with king exposure (castled + pawn shields moved) — a soft label.
- **Endgame technique**: many small leaks in endgame phase (high ACPL with low blunder rate).

We always include *evidence examples* for each claimed weakness:
- FEN
- user move
- engine best move
- short PV
- eval swing

### 6) LLM report generation (optional but recommended)
LLM is used for **summarization and coaching narrative**, not chess correctness.

Both LLM and deterministic reports are always generated:
- `report.md` — LLM narrative (when enabled), otherwise deterministic
- `summary.md` — deterministic stats report (always written)

If LLM is enabled:
- Input to LLM must be a compact "evidence packet":
  - summary.json (aggregates)
  - top examples (FEN + best line + eval swing)
- The LLM must never invent specific moves not present in the packet.
- Reports include opponent usernames for easy cross-reference with Chess.com.

If LLM is disabled:
- Generate a deterministic report template from aggregates + examples.

LLM configuration:
- Default: off unless user sets `LLM_PROVIDER` (or `--llm on`)
- Support at least:
  - OpenAI-compatible endpoint via env vars
  - local model via user-specified command (optional later)

### 7) Single-game analysis (optional)
Analyze one game at a time with historical context from the most recent bulk run.

Game selection:
- `--game latest` — most recent game (always fetches fresh from Chess.com API)
- `--game -N` — N games ago (always fetches fresh)
- `--game <id>` — by game ID (checks cache first)
- `--game <url>` — by Chess.com URL (checks cache first)

Pipeline:
1. Resolve selector and fetch game (API for latest/offset, cache+API for ID/URL)
2. Load or run Stockfish analysis (reuses per-game cache)
3. Load historical context (latest bulk run's summary.json)
4. Compute single-game stats (phase breakdown, swing moves, motifs)
5. Generate report:
   - LLM mode: sends evidence packet + previous bulk report as context, framed as a follow-up from the same coach
   - Deterministic mode: structured stats with historical comparison
6. Write output to `out/<username>/single_<game_id>_<timestamp>/`

---

## CLI contract

### One-button default
   blunder-butler <username>


Behavior:
- Fetch last 90 days of rated games, all time controls, max 100 games.
- Analyze only the user's moves.
- 100ms/move Stockfish.
- Produce report at `out/<username>/<timestamp>/report/report.md`.

### Single-game mode
   blunder-butler <username> --game latest

Behavior:
- Fetch fresh games from Chess.com API (for `latest`/offset selectors).
- Analyze one game with Stockfish (reuses per-game cache).
- Load historical context from most recent bulk run.
- Produce report at `out/<username>/single_<game_id>_<timestamp>/report.md`.

### Common knobs
- `--game latest|-N|<id>|<url>` (single-game mode)
- `--time-control bullet|blitz|rapid|daily|all`
- `--since 30d` / `--until YYYY-MM-DD`
- `--max-games 1000`
- `--engine-time-ms 50|200|500`
- `--depth 12` (mutually exclusive with time-ms)
- `--threads N`
- `--both-sides`
- `--llm on|off`
- `--openings-only` / `--endgames-only` (debugging)
- `--resume` (use cache where possible)

### Exit codes
- 0: success
- 2: user error (bad args)
- 3: network/API error
- 4: engine error (Stockfish not found / failed)
- 5: unexpected error

---

## Defaults rationale

Defaults are tuned for:
- **Speed**: finishes in minutes for ~300 games.
- **Signal quality**: enough depth/time to identify blunders and phase-level patterns.
- **Local reproducibility**: cached analysis and deterministic aggregation.

---

## Engineering principles

### Correctness
- Engine is source of truth for eval deltas; LLM never decides “best move.”
- Always normalize eval from the player perspective.
- Validate PGN parsing; skip invalid games rather than crashing.

### Performance
- Cache by FEN + engine settings hash.
- Multiprocessing for engine eval when safe (one engine per worker).
- Optional “two-pass” analysis:
  - quick pass all moves
  - deeper pass only on candidate blunders (CPL above threshold)

### Observability
- Logs are structured and helpful.
- Each run writes `run.json` containing:
  - inputs, filters, engine settings, counts, timings, git commit hash.

### Safety & privacy
- Runs locally.
- Only contacts Chess.com API and optional LLM endpoint (if configured).
- No uploading games anywhere by default.

---

## What we should discuss next (if anything)
Not blockers, but choices that shape the MVP:

1) **Language + stack**: Python is the shortest path; do we want a future Node CLI?
2) **Report quality baseline**: ship deterministic report first, then add LLM as enhancement.
3) **Caching format**: JSONL is simplest; SQLite is nicer for querying.
4) **Time control parsing**: Chess.com time control strings can be messy; define a robust mapper.

---

## Milestones

### v0.1 (MVP) ✓
- `blunder-butler <username>` works end-to-end
- outputs raw pgn + report.md
- phase ACPL and blunder rates by time control

### v0.2 ✓
- stable cache + resume
- motif heuristics with evidence examples
- deterministic report + optional LLM narrative
- single-game analysis mode (`--game`)
- historical context comparison in single-game reports
- opponent names in reports for easy game lookup

### v0.3
- lightweight local UI (optional) or richer markdown (charts, tables)
- deeper example selection (cluster similar mistakes)

