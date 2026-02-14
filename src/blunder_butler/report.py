"""Deterministic Markdown report generation."""

from __future__ import annotations

from .models import MoveFlag, Phase, Summary


def _phase_label(phase: Phase) -> str:
    return phase.value.capitalize()


def _flag_emoji(flag: MoveFlag) -> str:
    return {
        MoveFlag.BLUNDER: "??",
        MoveFlag.MISTAKE: "?",
        MoveFlag.INACCURACY: "?!",
        MoveFlag.GOOD: "",
        MoveFlag.BEST: "!",
    }.get(flag, "")


def generate_report(summary: Summary) -> str:
    """Generate a deterministic Markdown coaching report."""
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
            if motif.examples:
                lines.append("**Examples:**")
                lines.append("")
                for i, ex in enumerate(motif.examples, 1):
                    lines.append(f"{i}. **Game {ex.game_id}, move {ex.ply}**")
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
        lines.append("| # | Game | Ply | Phase | Played | Best | CPL |")
        lines.append("|---|------|-----|-------|--------|------|-----|")
        for i, sm in enumerate(summary.swing_moves, 1):
            lines.append(
                f"| {i} | {sm.game_id[:8]} | {sm.ply} | {_phase_label(sm.phase)} "
                f"| {sm.move_san} | {sm.best_move_san} | {sm.cpl} |"
            )
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

    # Motif-specific
    for motif in summary.motifs:
        if motif.name == "Hanging Pieces" and motif.count >= 3:
            recs.append(
                "**Board awareness:** You frequently leave pieces hanging. "
                "Before finalizing a move, scan the board for undefended pieces."
            )
        elif motif.name == "Missed Tactics" and motif.count >= 3:
            recs.append(
                "**Tactical training:** You're missing tactical opportunities. "
                "Spend 15-20 minutes daily on tactical puzzles to sharpen pattern recognition."
            )

    if not recs:
        recs.append("Keep playing and analyzing your games to identify patterns in your play.")

    return recs
