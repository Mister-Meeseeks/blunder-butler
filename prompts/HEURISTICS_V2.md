# heuristics_v2.md

Heuristics V2 for the local-first Chess.com coach pipeline.

This file defines **actionable, engine-grounded heuristics** to identify weaknesses (especially for ~600–1000 players), plus **time-management analytics** when PGNs contain clock tags.

V2 goals:
- Increase coaching value without pretending to be “perfect motif recognition.”
- Keep everything **grounded in Stockfish outputs + measurable signals**.
- Provide **evidence examples** for every claim.

Non-goals:
- Full tactical motif classification (fork/pin/skewer) with high accuracy.
- “Human intent” inference (e.g., what the user was thinking).
- Opening repertoire theory.

---

## 0) Shared definitions

### 0.1 Evaluation normalization
We evaluate a single “target player” (the user) across games, regardless of color.

Define:
- `pov` = target player (user)
- `stm` = side to move for the position
- Engine gives eval `E` in centipawns (cp) from side-to-move’s perspective (depends on engine interface).
- Normalize to POV:
  - `E_pov = +E` if POV is the side engine eval is for
  - `E_pov = -E` otherwise

Implementation guidance:
- If using python-chess, Stockfish score is typically from side-to-move; confirm and normalize.
- Store:
  - `eval_before_pov`
  - `eval_after_user_move_pov`
  - `eval_best_pov` (best line for POV on their turn)

### 0.2 Centipawn Loss (CPL)
For a move made by POV:

`CPL = max(0, eval_best_pov - eval_after_user_move_pov)`

If mate scores:
- Prefer a separate `mate` channel (see 0.3). If a move converts a mate to non-mate, treat as large CPL using a cap (e.g., 2000cp) plus a `mate_drop=true` flag.

Store:
- `cpl_cp` (int)
- `mate_before`, `mate_after`, `mate_best` (optional)
- `is_mate_event` boolean

### 0.3 Mate handling rules
Represent engine score as:
- `type: "cp"` with `value_cp`
- or `type: "mate"` with `value_mate_plies` (positive = mating for POV, negative = getting mated)

Derived flags:
- `missed_mate` if best is mate-for-POV and played move is not (or mate distance worsened materially).
- `allowed_mate` if before was non-mate but after move leads to mate-against-POV in best reply PV.

Thresholds:
- Consider mate as “imminent” if `abs(value_mate_plies) <= 12` (configurable).

---

## 1) Phase detection (Opening / Middlegame / Endgame)

We label each POV move as one of: `opening`, `middlegame`, `endgame`.

### 1.1 Material-based phase score (recommended)
Compute a continuous “phase” score based on remaining non-pawn material:
- Use common weights:
  - Queen = 4
  - Rook = 2
  - Bishop/Knight = 1
- Sum for both sides, normalize by starting sum (e.g., 24 using Q=4,R=2,B/N=1).

`phase = clamp(sum_remaining / sum_start, 0..1)`

Then:
- `endgame` if `phase <= 0.25` OR (no queens on board AND phase <= 0.35)
- `opening` if move_number <= 10 (POV full-move count) AND `phase >= 0.85`
- else `middlegame`

### 1.2 Fallback heuristic (if material calc unavailable)
- `opening` = plies 1–20 (full move <= 10)
- `endgame` = total pieces (excluding kings) <= 6 OR queens off and total pieces <= 10
- else `middlegame`

Store:
- `phase_label`
- `phase_score` if computed

---

## 2) Error severity bins

Default bins (tuned to be actionable for 600–1000):
- `inaccuracy` if `CPL >= 50`
- `mistake` if `CPL >= 150`
- `blunder` if `CPL >= 300`

Additional “catastrophic”:
- `drop_piece` if material swing >= minor piece (see 3.1)
- `mate_miss` / `mate_allow` flags (see 0.3)

Store:
- `severity`: one of `ok|inaccuracy|mistake|blunder`
- plus special flags

---

## 3) Core weakness heuristics (V2)

Each heuristic produces:
- a label (string)
- a confidence score (0–1)
- evidence references (move ids / positions)
- optional metadata (e.g., piece type lost, square)

### 3.1 Hang / Drop (immediate material loss)
User makes a move; engine’s best reply immediately wins material cleanly.

Signals:
- In PV for opponent’s best reply, first move is a capture (`x`) that wins a piece/pawn.
- Or static material delta between `fen_before` and after best reply indicates material loss.

Practical implementation options:
A) PV-based: parse the first reply move; if it is capture and after that capture POV is down material compared to before user move, label as hang.
B) Two-eval + material: if `CPL >= 300` AND material decreases by >= 3 (minor piece) within next 1 ply in best line, label hang.

Metadata:
- `lost_piece`: {pawn, knight, bishop, rook, queen}
- `lost_square`
- `captured_by_piece` (if easily derivable)

Confidence:
- 0.9 if material loss visible in 1 ply
- 0.7 if visible within 3 plies of PV

User-facing advice template:
- “You frequently leave pieces en prise (unprotected). Do a 3-second ‘hanging piece scan’ before moving.”

### 3.2 Missed forcing move (Checks/Captures/Threats)
POV had a forcing move (often check/capture) that wins significant advantage; played a quiet move.

Signals:
- `CPL >= 200` AND best move is a **check** or **capture** (or immediate tactical threat detected via PV).
- PV shows material win or mate within a short horizon (<= 8 plies).

Implementation:
- Compute move features for engine best move:
  - `is_check_best`
  - `is_capture_best`
  - `gives_threat_best` (optional, see 3.3)
- If `is_check_best OR is_capture_best` and CPL large, label.

Confidence:
- 0.8 if best is check/capture and PV wins material within 6 plies
- 0.6 otherwise

Advice template:
- “In critical positions, start by looking for forcing moves: checks, captures, threats.”

### 3.3 Ignored opponent threat / Defensive miss
User plays a move that allows opponent a forcing sequence (check/capture) leading to large loss.

Signals:
- After user move, opponent best reply is check/capture and leads to big eval swing.
- `CPL >= 250` AND opponent PV begins with check/capture AND results in material win or mate soon.

Implementation:
- For the best reply move (opponent), compute `is_check_reply` / `is_capture_reply`.
- Optionally compare `eval_before_pov` vs `eval_after_user_move_pov` for magnitude.

Confidence:
- 0.85 if opponent’s first reply is check/capture and PV is forcing
- 0.65 if forcing appears by ply 3

Advice template:
- “After every opponent move: ask ‘what does that attack?’ and ‘what are their forcing moves next?’”

### 3.4 Opening principle flags (only high-signal)
We avoid theory; we flag only obvious anti-patterns in first ~10 moves.

Flags (each independent):
- `early_queen_moves`: queen moved before move 6 AND development score low
- `repeat_piece`: same piece moved >= 2 times in first 8 moves (excluding recaptures)
- `no_castle_long`: king not castled by move 12 AND eval trend deteriorates
- `neglect_development`: by move 8, fewer than 2 minor pieces developed and eval dropping

Implementation notes:
- Development score: count unique minor pieces that have moved from original squares and are not returned.
- “Repeat piece” requires tracking piece identity (from-square) across early moves.

Confidence:
- 0.7 if flag + measurable eval harm (e.g., average CPL in opening elevated)
- 0.5 if flag only

Advice templates:
- “Develop minors once each; avoid moving the same piece repeatedly early.”
- “Delay queen adventures until pieces are out and king is safe.”

### 3.5 King safety weakening (pawn shield / king exposure)
Flag when a pawn move near the castled king correlates with major eval loss.

Signals:
- King is castled (or committed) and user plays pawn move on f/g/h files (for short castle) or a/b/c (for long).
- Move creates weaknesses: `g4`, `h4`, `f3`, `g3` etc.
- `CPL >= 200` OR subsequent PV begins with checks near king.

Implementation:
- Determine king side (short/long/center).
- Identify “shield pawns” adjacent to king.
- If user moved a shield pawn 1–2 squares and CPL large, label.

Confidence:
- 0.75 if PV contains immediate checks targeting king
- 0.55 otherwise

Advice:
- “Avoid loosening pawns in front of your king unless you see a clear reason.”

### 3.6 Win material then give it back (conversion / retention)
Common at this level: a good tactic followed by immediate blunder.

Signals:
- Detect a “material win event” (eval spikes up by >= +200cp or material +3/+5).
- Within next 1–3 user moves, material advantage decreases by >= 3 or eval collapses by >= 250cp.
- Not explained by forced sequence (optional).

Implementation:
- Track rolling window per game for POV.
- Identify peaks and subsequent drawdowns.

Confidence:
- 0.8 if material delta is objective
- 0.6 if only eval-based

Advice:
- “After winning material: slow down, trade pieces, avoid tactics, and check for counterplay.”

### 3.7 Endgame technique leak (many small losses)
Not about one blunder; it’s about consistent inaccuracy in endgames.

Signals:
- In `endgame` phase, ACPL is high (e.g., >= 80) but blunder rate is low (few CPL>=300).
- Or repeated missed “obvious” improvements: king activity, pawn pushes, rook activity (heuristic).

Implementation:
- Compute per-phase ACPL and severity distribution.
- Label if endgame has disproportionate share of mistakes relative to midgame.

Confidence:
- 0.7 if statistical pattern is strong (n_moves_endgame >= 80)
- 0.4 if sample small

Advice:
- “In endgames: activate king first; push passed pawns; avoid creating new weaknesses.”

### 3.8 Basic mate technique gaps (K+Q/K+R etc.)
If engine shows mate-in-N repeatedly in simple material but user fails for many moves.

Signals:
- In endgame positions with K+Q vs K or K+R vs K (or similar simple mates),
- engine reports mate-for-POV for multiple consecutive POV moves, but mate distance doesn’t improve.

Implementation:
- Detect material pattern (tablebase-like).
- If mate present for >= 5 consecutive POV turns and mate distance doesn’t shrink meaningfully, label.

Confidence:
- 0.9 (very objective)
Advice:
- “Spend 15 minutes learning basic mates; it converts many won games.”

---

## 4) Time management analytics (V2)

Time advice is only enabled if the PGN contains clock annotations for a sufficient fraction of moves.

### 4.1 Clock tag parsing
Support extracting remaining clock from PGN comments:
- `[%clk H:MM:SS]` (common)
- optionally `[%emt ...]` if present (elapsed move time)

For each ply, store:
- `clk_remain_s` (float/int seconds remaining after that ply)

Derive per POV move:
- `dt_s` (time spent) = previous POV clock remaining - current POV clock remaining + increment (if known)
- If increment unknown, `dt_s = max(0, prev - curr)`.

### 4.2 Time-control parsing
Use PGN headers if available:
- `TimeControl` e.g., `600+5`, `180`, `-` (daily), etc.
Store:
- `tc_initial_s`, `tc_increment_s`, `tc_type`

If daily or unknown, time-management section is disabled by default.

### 4.3 Enable/disable criteria
Enable time analytics if:
- For included games, at least `clock_coverage >= 0.70` on POV moves,
- AND time control is not daily/unknown.

If coverage is 0.30–0.70:
- Show limited stats with a warning (partial coverage).

### 4.4 Core time metrics (per time-control bucket + overall)
Compute for POV moves:
- `avg_dt_s`, `median_dt_s`, `p90_dt_s`
- `dt_s by phase` (opening/mid/end)
- `time_trouble_rate`: fraction of moves where `clk_remain_s <= max(10, 0.1 * tc_initial_s)`
- `blunder_rate_in_time_trouble` vs not
- `blunder_rate_on_insta_moves`:
  - define insta = `dt_s <= 2.0` seconds (configurable by time control)

Report recommended default thresholds by time control:
- bullet: insta <= 1.0s, time-trouble <= 5s
- blitz: insta <= 2.0s, time-trouble <= 10s
- rapid: insta <= 3.0s, time-trouble <= 30s

### 4.5 “Critical moment” time allocation
We want to answer: “Did you spend time when the position demanded it?”

Define a move as **critical** if any of:
- `CPL >= 150` (you made a significant mistake)
- OR engine best-vs-2nd-best gap is large (requires MultiPV=2):
  - `gap_cp = eval_best - eval_2nd_best >= 120`
- OR eval volatility potential (approx):
  - `abs(eval_before_pov) <= 200` (unclear position) AND `CPL >= 200`

Then compute:
- `avg_dt_s(critical)` vs `avg_dt_s(non_critical)`
- fraction of critical moves played as insta-moves
- top 10 critical blunders with `dt_s`, `clk_remain_s`

Advice templates:
- “Your biggest blunders happen on insta-moves. Add a 2-second scan on every move.”
- “You spend too much time early and arrive in time trouble; shift thinking to critical middlegame moments.”

### 4.6 Overthinking vs autopilot
Heuristic classification per blunder:
- **autopilot blunder**: blunder + insta move
- **calculation failure**: blunder + long think (`dt_s >= p90_dt_s` for that time control)

Report:
- count and examples of each category
- suggested fix:
  - autopilot → pre-move safety checklist
  - calculation failure → simplify candidate moves, focus on forcing lines

---

## 5) Evidence selection & clustering

### 5.1 Always include evidence
Every weakness claim must show at least:
- N examples (default 3–5) with:
  - FEN
  - user move (SAN + UCI)
  - engine best move
  - eval before/after
  - short PV (6–10 plies)
  - time stats if available (`dt_s`, `clk_remain_s`)

### 5.2 Choose examples that are representative
We avoid picking 5 examples from the same game or same opening line.

Rules:
- max 1 example per game for a given label (default)
- diversify by phase and time control where possible

### 5.3 Light clustering (optional)
To reduce repetition, cluster by:
- `lost_piece` type (hangs)
- “reply is check” vs “reply is capture” (defensive misses)
- king side (king safety)
- opening principle flag type

---

## 6) Scoring & prioritization of weaknesses

We need a rank order for “top 3 Elo leaks.”

For each label, compute an impact score:

`impact = frequency_weight * avg_cpl_weight * coverage_weight`

Suggested:
- frequency_weight = min(1, count / 20)
- avg_cpl_weight = min(1, avg_cpl / 300)
- coverage_weight = min(1, unique_games / 10)

Then sort and pick top K (default 5).
Always include:
- “hang/drop” if present above minimal frequency (>= 3 occurrences), even if not top by impact.

---

## 7) Recommended defaults for 600–1000 report

Use these as “beginner-friendly defaults”:
- severity bins: 50 / 150 / 300 cp
- example count per top weakness: 4
- show “Habits” section derived from top 3 labels:
  - Hanging scan
  - Forcing moves scan
  - Threat response scan
- time section enabled only with >=70% clock coverage

---

## 8) Testing & validation checklist (engineers)

### 8.1 Unit tests
- Eval normalization sanity: same position mirrored gives sign flip.
- CPL non-negative and stable under normalization.
- Phase labeling consistent for simple material setups.
- Clock parsing handles:
  - missing tags
  - malformed tags
  - mixed formats

### 8.2 Golden PGN fixtures
Include a few small PGNs:
- one with clock tags
- one without
- one with daily time control
- one containing a clear hang, missed mate, and early queen adventure

### 8.3 Quality checks (manual)
- For top 10 worst moves, verify:
  - the best move and PV match Stockfish
  - label is plausible
  - advice text references only what evidence supports

---

## 9) Config surface (for CLI knobs later)

Expose these as config (with defaults):
- severity thresholds: inaccuracy/mistake/blunder
- engine budget: time_ms or depth
- MultiPV: 1 (default), 2 for critical-gap
- clock coverage threshold: 0.70
- insta thresholds by time control
- phase thresholds for endgame
- max examples per label

---

## 10) Output schema additions (suggested)

Add to per-move record:
- `phase_label`, `phase_score`
- `severity`
- `labels[]`: list of `{name, confidence, meta}`
- clock:
  - `clk_remain_s` (if parsed)
  - `dt_s` (derived for POV moves)

Add to summary stats:
- time usage tables per time control
- blunder rates conditioned on time states (insta, time-trouble, critical)
- top labels with impact scores and example ids

