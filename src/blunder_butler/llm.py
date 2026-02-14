"""Optional LLM-powered narrative report generation."""

from __future__ import annotations

import json
import os

import requests

from .config import Config
from .log import get_logger
from .models import Summary
from .report import generate_report


def _build_evidence_packet(summary: Summary) -> str:
    """Build a compact evidence packet for the LLM."""
    packet = {
        "username": summary.username,
        "total_games": summary.total_games,
        "total_moves": summary.total_moves,
        "overall_acpl": round(summary.acpl, 1),
        "phase_stats": [ps.to_dict() for ps in summary.phase_stats if ps.total_moves > 0],
        "time_control_stats": [tc.to_dict() for tc in summary.time_control_stats],
        "motifs": [m.to_dict() for m in summary.motifs],
        "worst_moves": [s.to_dict() for s in summary.swing_moves[:5]],
    }
    return json.dumps(packet, indent=2)


SYSTEM_PROMPT = """You are an experienced chess coach writing a personalized coaching report.
You will receive engine analysis data for a player's recent games. Your job is to:
1. Summarize their strengths and weaknesses in a friendly, encouraging tone
2. Identify the most impactful areas for improvement
3. Give specific, actionable training recommendations
4. Reference concrete examples from the data (positions, moves, eval swings)

IMPORTANT: Never invent specific moves or positions not present in the data.
Keep the report concise (under 1000 words). Use Markdown formatting."""


def generate_llm_report(summary: Summary, config: Config) -> str | None:
    """Generate an LLM-powered narrative report. Returns None on failure."""
    logger = get_logger()

    endpoint = config.llm_endpoint or os.environ.get("LLM_ENDPOINT", "")
    api_key = config.llm_api_key or os.environ.get("LLM_API_KEY", "")
    model = config.llm_model or os.environ.get("LLM_MODEL", "gpt-4")

    if not endpoint:
        logger.warning("No LLM endpoint configured, falling back to deterministic report")
        return None

    evidence = _build_evidence_packet(summary)
    user_prompt = f"Generate a coaching report for this player's chess analysis data:\n\n{evidence}"

    try:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 2000,
        }

        resp = requests.post(
            endpoint.rstrip("/") + "/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        logger.info("LLM report generated successfully")
        return content

    except Exception as e:
        logger.warning("LLM report generation failed: %s. Falling back to deterministic report.", e)
        return None


def generate_report_with_llm_fallback(summary: Summary, config: Config) -> str:
    """Generate report: try LLM first if enabled, fall back to deterministic."""
    if config.llm == "on":
        llm_report = generate_llm_report(summary, config)
        if llm_report:
            return llm_report
    return generate_report(summary)
