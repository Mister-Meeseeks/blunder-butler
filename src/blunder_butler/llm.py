"""Optional LLM-powered narrative report generation."""

from __future__ import annotations

import json
import os
import time

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

    logger.info("LLM request: model=%s, evidence=%d chars", model, len(evidence))

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

        url = endpoint.rstrip("/") + "/chat/completions"
        t0 = time.monotonic()

        resp = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=(10, 30),
            stream=True,
        )

        logger.info("LLM connected (HTTP %d, %.1fs), waiting for model to finish thinking...",
                     resp.status_code, time.monotonic() - t0)

        max_wait = 300  # wall-clock seconds
        chunks = []
        for chunk in resp.iter_content(chunk_size=256):
            elapsed = time.monotonic() - t0
            if not chunk.strip():
                # OpenRouter keepalive whitespace — ignore but check deadline
                if elapsed > max_wait:
                    logger.warning("LLM request timed out after %.0fs", elapsed)
                    resp.close()
                    return None
                continue
            chunks.append(chunk)

        if not chunks:
            logger.warning("LLM response contained only keepalive whitespace, no content")
            return None

        body = b"".join(chunks)
        elapsed = time.monotonic() - t0
        logger.info("LLM response complete in %.1fs (%d bytes)", elapsed, len(body))

        if resp.status_code != 200:
            logger.warning("LLM endpoint returned HTTP %d: %s", resp.status_code, body.decode(errors="replace")[:500])
            return None
        data = json.loads(body)
        content = data["choices"][0]["message"]["content"]
        logger.info("LLM report generated (%d chars)", len(content) if content else 0)
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
