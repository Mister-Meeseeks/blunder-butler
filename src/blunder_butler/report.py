"""Deterministic Markdown report generation."""

from __future__ import annotations

from .models import MoveFlag, Phase, Summary, TimeStats


def _phase_label(phase: Phase) -> str:
    return phase.value.capitalize()


_SUBTYPE_LABELS = {
    "hang_en_prise": "Piece left en prise",
    "allowed_forcing_check": "Allowed forcing check",
    "allowed_forcing_capture": "Allowed forcing capture",
    "missed_forcing_check": "Missed forcing check",
    "missed_forcing_capture": "Missed forcing capture",
    "motif_knight_fork": "Missed knight fork",
}


def _subtype_label(subtype: str) -> str:
    return _SUBTYPE_LABELS.get(subtype, subtype)


def _flag_emoji(flag: MoveFlag) -> str:
    return {
        MoveFlag.BLUNDER: "??",
        MoveFlag.MISTAKE: "?",
        MoveFlag.INACCURACY: "?!",
        MoveFlag.GOOD: "",
        MoveFlag.BEST: "!",
    }.get(flag, "")


def _format_time_section(stats: TimeStats) -> str:
    """Format the time management analytics section."""
    lines: list[str] = []
    lines.append("## Time Management")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Avg time/move | {stats.avg_dt_s:.1f}s |")
    lines.append(f"| Median time/move | {stats.median_dt_s:.1f}s |")
    lines.append(f"| 90th percentile | {stats.p90_dt_s:.1f}s |")
    lines.append(f"| Time trouble rate | {stats.time_trouble_rate:.1%} |")
    lines.append(f"| Clock coverage | {stats.clock_coverage:.1%} |")
    lines.append("")

    lines.append("**Blunder patterns by speed:**")
    lines.append("")
    lines.append(f"- Fast moves (autopilot): {stats.blunder_rate_insta:.1%} blunder rate "
                 f"({stats.autopilot_blunders} blunders)")
    lines.append(f"- Normal/slow moves: {stats.blunder_rate_normal:.1%} blunder rate "
                 f"({stats.calculation_failures} calculation failures)")
    lines.append("")

    if stats.autopilot_blunders > stats.calculation_failures:
        lines.append(
            "**Pattern:** Most blunders come from moves played too quickly. "
            "Slow down and check for threats before committing."
        )
    elif stats.calculation_failures > stats.autopilot_blunders:
        lines.append(
            "**Pattern:** Most blunders come from positions where you spent significant time. "
            "Focus on improving calculation technique and candidate move selection."
        )
    else:
        lines.append(
            "**Pattern:** Blunders are evenly split between fast and slow moves. "
            "Work on both time discipline and calculation depth."
        )

    return "\n".join(lines)


def _opponent_map(summary: Summary) -> dict[str, str]:
    """Build a game_id -> opponent name lookup."""
    return {gs.game_id: gs.opponent for gs in summary.game_summaries}


def generate_report(summary: Summary) -> str:
    """Generate a deterministic Markdown coaching report."""
    opponents = _opponent_map(summary)
    lines: list[str] = []

    lines.append(f"# Chess Coaching Report: {summary.username}")
    lines.append("")
    lines.append(f"**Games analyzed:** {summary.total_games}")
    lines.append(f"**Total moves analyzed:** {summary.total_moves}")
    lines.append(f"**Overall ACPL:** {summary.acpl:.1f}")
    lines.append("")

    # Overall summary table
    lines.append("## Overall Performance")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Games | {summary.total_games} |")
    lines.append(f"| Moves Analyzed | {summary.total_moves} |")
    lines.append(f"| ACPL | {summary.acpl:.1f} |")

    total_blunders = sum(ps.blunders for ps in summary.phase_stats)
    total_mistakes = sum(ps.mistakes for ps in summary.phase_stats)
    total_inaccuracies = sum(ps.inaccuracies for ps in summary.phase_stats)
    lines.append(f"| Blunders | {total_blunders} |")
    lines.append(f"| Mistakes | {total_mistakes} |")
    lines.append(f"| Inaccuracies | {total_inaccuracies} |")
    lines.append("")

    # Phase breakdown
    lines.append("## Performance by Game Phase")
    lines.append("")
    lines.append("| Phase | Moves | ACPL | Blunders/100 | Mistakes/100 | Inaccuracies/100 |")
    lines.append("|-------|-------|------|-------------|-------------|-----------------|")
    for ps in summary.phase_stats:
        if ps.total_moves == 0:
            continue
        lines.append(
            f"| {_phase_label(ps.phase)} | {ps.total_moves} | {ps.acpl:.1f} "
            f"| {ps.blunders_per_100:.1f} | {ps.mistakes_per_100:.1f} "
            f"| {ps.inaccuracies_per_100:.1f} |"
        )
    lines.append("")

    # Weakest phase
    active_phases = [ps for ps in summary.phase_stats if ps.total_moves > 0]
    if active_phases:
        worst = max(active_phases, key=lambda ps: ps.acpl)
        lines.append(
            f"**Weakest phase:** {_phase_label(worst.phase)} "
            f"(ACPL {worst.acpl:.1f}, {worst.blunders_per_100:.1f} blunders/100 moves)"
        )
        lines.append("")

    # Opening ACPL by color
    if summary.opening_acpl_white is not None and summary.opening_acpl_black is not None:
        lines.append("### Opening ACPL by Color")
        lines.append("")
        lines.append("| Color | ACPL |")
        lines.append("|-------|------|")
        lines.append(f"| White | {summary.opening_acpl_white:.1f} |")
        lines.append(f"| Black | {summary.opening_acpl_black:.1f} |")
        lines.append("")
        diff = abs(summary.opening_acpl_white - summary.opening_acpl_black)
        if diff > 15:
            worse_color = "White" if summary.opening_acpl_white > summary.opening_acpl_black else "Black"
            lines.append(
                f"**Note:** Your opening play as {worse_color} is notably weaker. "
                f"Consider studying your {worse_color} repertoire specifically."
            )
            lines.append("")

    # Time control breakdown
    if summary.time_control_stats:
        lines.append("## Performance by Time Control")
        lines.append("")
        lines.append("| Time Control | Games | Moves | ACPL | Blunders/100 | Mistakes/100 |")
        lines.append("|-------------|-------|-------|------|-------------|-------------|")
        for tc in summary.time_control_stats:
            lines.append(
                f"| {tc.time_control.value.capitalize()} | {tc.games} | {tc.total_moves} "
                f"| {tc.acpl:.1f} | {tc.blunders_per_100:.1f} | {tc.mistakes_per_100:.1f} |"
            )
        lines.append("")

    # Key weaknesses (motifs)
    if summary.motifs:
        lines.append("## Key Weaknesses")
        lines.append("")
        for motif in summary.motifs:
            lines.append(f"### {motif.name} ({motif.count} occurrences)")
            lines.append("")
            lines.append(motif.description)
            lines.append("")
            # Subtype breakdown (only if count >= 5 per spec)
            if motif.subtype_counts and motif.count >= 5:
                lines.append("**Breakdown:**")
                lines.append("")
                for st, cnt in sorted(motif.subtype_counts.items(),
                                      key=lambda x: x[1], reverse=True):
                    label = _subtype_label(st)
                    lines.append(f"- {label}: {cnt}")
                lines.append("")
            if motif.examples:
                lines.append("**Examples:**")
                lines.append("")
                for i, ex in enumerate(motif.examples, 1):
                    subtype_str = f" [{_subtype_label(ex.subtype)}]" if ex.subtype else ""
                    opp = opponents.get(ex.game_id, "")
                    opp_str = f" vs {opp}" if opp else ""
                    lines.append(f"{i}. **Game {ex.game_id[:8]}{opp_str}, move {ex.ply}**{subtype_str}")
                    lines.append(f"   - Position: `{ex.fen}`")
                    lines.append(f"   - Played: {ex.move_san}")
                    lines.append(f"   - Best: {ex.best_move_san}")
                    lines.append(f"   - Eval swing: {ex.eval_swing} cp")
                    if ex.game_url:
                        lines.append(f"   - [View game]({ex.game_url})")
                    lines.append("")

    # Worst moves
    if summary.swing_moves:
        lines.append("## Worst Moves")
        lines.append("")
        lines.append("| # | Game | Opponent | Ply | Phase | Played | Best | CPL |")
        lines.append("|---|------|----------|-----|-------|--------|------|-----|")
        for i, sm in enumerate(summary.swing_moves, 1):
            opp = opponents.get(sm.game_id, "")
            lines.append(
                f"| {i} | {sm.game_id[:8]} | {opp} | {sm.ply} | {_phase_label(sm.phase)} "
                f"| {sm.move_san} | {sm.best_move_san} | {sm.cpl} |"
            )
        lines.append("")

    # Time management
    if summary.time_stats:
        lines.append(_format_time_section(summary.time_stats))
        lines.append("")

    # Training recommendations
    lines.append("## Training Recommendations")
    lines.append("")
    recommendations = _generate_recommendations(summary)
    for i, rec in enumerate(recommendations, 1):
        lines.append(f"{i}. {rec}")
    lines.append("")

    lines.append("---")
    lines.append("*Generated by Blunder Butler v0.1*")
    lines.append("")

    return "\n".join(lines)


def _generate_recommendations(summary: Summary) -> list[str]:
    """Generate rule-based training recommendations."""
    recs = []
    active_phases = [ps for ps in summary.phase_stats if ps.total_moves > 0]

    if not active_phases:
        return ["Play more games to get meaningful analysis."]

    worst_phase = max(active_phases, key=lambda ps: ps.acpl)

    # Phase-specific recommendations
    if worst_phase.phase == Phase.OPENING:
        recs.append(
            "**Study openings:** Your opening play shows the highest error rate. "
            "Focus on understanding the principles behind your main openings rather than memorizing lines."
        )
    elif worst_phase.phase == Phase.MIDDLEGAME:
        recs.append(
            "**Improve middlegame calculation:** Your middlegame shows the most inaccuracies. "
            "Practice tactical puzzles focusing on candidate moves and calculation depth."
        )
    elif worst_phase.phase == Phase.ENDGAME:
        recs.append(
            "**Study endgames:** Your endgame technique needs work. "
            "Focus on basic endgame principles: king activity, pawn structure, and piece coordination."
        )

    # Blunder-specific
    total_moves = sum(ps.total_moves for ps in active_phases)
    total_blunders = sum(ps.blunders for ps in active_phases)
    if total_moves > 0 and (total_blunders * 100 / total_moves) > 3:
        recs.append(
            "**Blunder check:** Before each move, ask yourself 'what does my opponent threaten?' "
            "Your blunder rate is elevated — a simple safety check will help."
        )

    # Time control specific
    if len(summary.time_control_stats) > 1:
        worst_tc = max(summary.time_control_stats, key=lambda tc: tc.acpl)
        best_tc = min(summary.time_control_stats, key=lambda tc: tc.acpl)
        if worst_tc.acpl > best_tc.acpl * 1.5:
            recs.append(
                f"**Time management:** Your play is significantly worse in "
                f"{worst_tc.time_control.value} ({worst_tc.acpl:.0f} ACPL) compared to "
                f"{best_tc.time_control.value} ({best_tc.acpl:.0f} ACPL). "
                f"Consider slowing down or playing longer time controls to improve."
            )

    # Motif-specific (with subtype refinements)
    for motif in summary.motifs:
        if motif.name == "Hanging Pieces" and motif.count >= 3:
            recs.append(
                "**Board awareness:** You frequently leave pieces hanging. "
                "Before finalizing a move, scan the board for undefended pieces."
            )
        elif motif.name == "Missed Tactics" and motif.count >= 3:
            st = motif.subtype_counts
            fork_count = st.get("motif_knight_fork", 0)
            check_count = st.get("missed_forcing_check", 0)
            capture_count = st.get("missed_forcing_capture", 0)
            if fork_count >= 3:
                recs.append(
                    "**Knight fork training:** You're repeatedly missing knight forks. "
                    "Practice puzzles that focus on double attacks, especially with knights."
                )
            elif check_count >= 3:
                recs.append(
                    "**Check first:** You're missing forcing checks that win material or deliver mate. "
                    "Always consider checks as candidate moves — they drastically limit your opponent's options."
                )
            elif capture_count >= 3:
                recs.append(
                    "**Capture awareness:** You're missing winning captures. "
                    "Before committing to a move, scan for captures that win material."
                )
            else:
                recs.append(
                    "**Tactical training:** You're missing tactical opportunities. "
                    "Spend 15-20 minutes daily on tactical puzzles to sharpen pattern recognition."
                )
        elif motif.name == "Ignored Threats" and motif.count >= 3:
            st = motif.subtype_counts
            check_count = st.get("allowed_forcing_check", 0)
            if check_count >= 3:
                recs.append(
                    "**Check defense:** You frequently allow opponent checks that lead to material loss. "
                    "Before each move, verify your king is not exposed to forcing sequences."
                )
            else:
                recs.append(
                    "**Threat awareness:** You frequently allow forcing moves (checks and captures). "
                    "Before each move, ask: 'What can my opponent do to me after this?'"
                )
        elif motif.name == "Material Givebacks" and motif.count >= 2:
            recs.append(
                "**Consolidation:** You win material but give it back shortly after. "
                "After winning material, focus on trades and simplification rather than attacking."
            )

    # Time-based recommendations
    if summary.time_stats:
        ts = summary.time_stats
        if ts.autopilot_blunders > ts.calculation_failures and ts.autopilot_blunders >= 3:
            recs.append(
                "**Slow down:** Most of your blunders happen on moves played too quickly. "
                "Take at least a few seconds to scan for opponent threats before every move."
            )
        elif ts.calculation_failures > ts.autopilot_blunders and ts.calculation_failures >= 3:
            recs.append(
                "**Improve calculation:** Your blunders tend to happen on moves where you think "
                "a long time. Practice structured calculation: identify candidate moves, check "
                "forcing lines first, and verify your final choice."
            )

    if not recs:
        recs.append("Keep playing and analyzing your games to identify patterns in your play.")

    return recs
