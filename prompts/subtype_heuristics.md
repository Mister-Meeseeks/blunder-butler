## Subtypes for core mistake classes (V2 add-on)

Goal: add **coarse, actionable** subtypes that (a) are fairly reliable from engine/PV + board features, and (b) change the training advice. Avoid overly granular “bishop vs knight” splits unless they are strongly supported (exception: knight forks).

Each detected event should emit:
- `subtype` (string enum)
- `confidence` (0–1)
- `meta` (optional: piece, squares, targets)
- and must have **evidence** (FEN + PV + eval swing).

---

### A) Hanging pieces — subtypes by mechanism

**A1) `hang_en_prise` (left undefended / underdefended)**
- Definition: POV’s move leaves a piece immediately capturable, and opponent’s best reply is that capture, with no compensation.
- Detection (high-confidence):
  - In opponent best reply (PV ply 1), move is capture of a POV piece.
  - Material after that capture is worse for POV by >= 3 (minor) or >= 5 (rook) or >= 9 (queen), OR `CPL >= 300` and material loss >= 3 within 1 ply.
- Meta:
  - `lost_piece_type`, `lost_square`, `captured_by_piece_type`
- Confidence:
  - 0.9 if material loss occurs at PV ply 1.

**A2) `hang_moved_defender` (overload / unguarded after moving a defender)**
- Definition: POV moved a piece that was defending another piece/square; opponent captures the newly-undefended target.
- Detection:
  - PV reply captures a different POV piece (not the moved one).
  - The captured target was defended by the moved piece in `fen_before` and is not defended by it after the move.
  - Material loss >= 3 within 1 ply OR `CPL >= 250`.
- Meta:
  - `moved_piece_from`, `moved_piece_to`, `target_square`, `target_piece_type`
- Confidence:
  - 0.8 if defender relationship can be proven via attack/defense map.

**A3) `hang_pinned_piece` (moved/used pinned piece leading to loss)**
- Definition: POV moves a pinned piece (absolute or practical) and loses significant material or allows mate.
- Detection:
  - Identify if the moved piece was pinned in `fen_before` (line piece attack through it to king/queen/rook).
  - `CPL >= 200` and PV shows immediate win for opponent (capture of queen/rook, forced mate, or large material loss) within 3 plies.
- Meta:
  - `pinned_piece_type`, `pin_line` (file/diagonal), `pinned_to` (king/queen/rook)
- Confidence:
  - 0.75 if pinned-to-king (absolute), 0.6 otherwise.

**A4) `hang_mate_defense` (grabbed material but allowed mate/decisive attack)**
- Definition: POV takes/attacks something while neglecting immediate mate threat or forced attack.
- Detection:
  - After POV move, opponent PV contains mate against POV within <= 12 plies OR eval swing to losing is large with forcing checks.
  - Often co-occurs with `allowed_forcing_check` or `allowed_mate_threat`.
- Meta:
  - `mate_in_plies`, `first_check_move`
- Confidence:
  - 0.8 if engine reports mate.

Note: avoid “hang_bishop vs hang_knight” unless presenting as a secondary descriptive stat (not a primary subtype).

---

### B) Missed tactics (offense) — subtypes by forcing class + optional motifs

**B1) `missed_forcing_check`**
- Definition: engine best move is a check that wins material or mates soon; POV played something else.
- Detection:
  - Best move gives check (`is_check_best=true`)
  - `CPL >= 200` OR best line is mate-for-POV within <= 12 plies.
- Confidence:
  - 0.85 if PV shows forced material win/mate within 6 plies.

**B2) `missed_forcing_capture`**
- Definition: engine best move is a capture that wins material (tactical or simply free piece).
- Detection:
  - `is_capture_best=true`
  - `CPL >= 150` and PV indicates net material gain within <= 4 plies (or immediate).
- Confidence:
  - 0.8 if net +3 material within 2 plies.

**B3) `missed_forcing_threat`**
- Definition: best move is not an immediate check/capture but creates a decisive threat (tactic, mate net, win of material).
- Detection:
  - `is_check_best=false` and `is_capture_best=false`
  - `CPL >= 250` and PV shows forced win/mate within <= 8 plies.
- Confidence:
  - 0.65 (threat recognition is noisier; require PV evidence).

**Optional motif labels (attach only when confident)**
These are best-effort and must be backed by PV patterns:
- `motif_fork` (preferably knight fork, see B4)
- `motif_pin`
- `motif_skewer`
- `motif_discovered_attack`
- `motif_back_rank`
- `motif_remove_defender`
- `motif_deflection`

**B4) `motif_knight_fork` (special-case: high value at 600–1000)**
- Detection:
  - In best line, a knight move by POV immediately attacks 2+ high-value targets (Q/R/K or Q+R etc.)
  - and PV shows material win within <= 4 plies.
- Confidence:
  - 0.85 (objective from attack map + PV).

---

### C) Not responding to threats (defense) — subtypes by opponent’s forcing reply + mechanisms

**C1) `allowed_forcing_check`**
- Definition: POV move allows opponent to start a forcing line with checks causing big loss.
- Detection:
  - Opponent best reply is check (`is_check_reply=true`)
  - and (mate against POV within <= 12 plies OR `CPL >= 250` with forcing PV).
- Confidence:
  - 0.85 if mate; 0.7 if material win via checks.

**C2) `allowed_forcing_capture`**
- Definition: POV move allows opponent to win material immediately via capture sequence.
- Detection:
  - Opponent best reply is capture (`is_capture_reply=true`)
  - net material loss for POV within <= 2 plies is >= 3 OR `CPL >= 300`.
- Confidence:
  - 0.85 if immediate material loss.

**C3) `allowed_mate_threat`**
- Definition: POV ignored a direct mate threat (often one-move or short forced).
- Detection:
  - After POV move, engine reports mate against POV within <= 12 plies (or mate-in-1/2).
- Confidence:
  - 0.9 when mate reported.

**Mechanism tags (secondary; attach when detectable)**
- `missed_knight_fork_threat`:
  - opponent best reply is a knight move that attacks 2+ high-value targets immediately and PV wins material soon.
- `missed_xray_line`:
  - opponent tactic is along file/diagonal (rook/bishop/queen) with an “x-ray” through a pinned/loose piece; PV shows win after a clearance or capture.
- `missed_attack_on_last_moved_piece`:
  - opponent best reply targets the piece POV just moved, and PV shows it cannot be adequately defended (common “moved into danger” issue).

Confidence guidance:
- 0.85 for `missed_knight_fork_threat` (attack map + PV)
- 0.6–0.7 for x-ray / last-moved-piece mechanisms (more context-dependent).

---

### Output guidance
For each top-level class (hang / missed tactic / defensive miss), prefer surfacing **mechanism subtypes** (A1–A4, B1–B3, C1–C3).
Motifs/mechanisms are additive tags:
- e.g., `missed_forcing_check` + `motif_back_rank`
- e.g., `allowed_forcing_capture` + `missed_xray_line`

Only show subtype breakdowns in the report if sample size is sufficient:
- default: `count >= 5` events for that family; otherwise keep it qualitative with a couple examples.

