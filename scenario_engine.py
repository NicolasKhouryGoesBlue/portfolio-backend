"""
scenario_engine.py

Takes a portfolio scenario description, computes estimated financial impact using
sector-weighted beta logic, calls Claude to interpret the results, and returns both
the raw numbers and the narrative.

Depends on: ANTHROPIC_API_KEY in .env, the anthropic library, and python-dotenv.
"""

import logging
import os
import re

import anthropic
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

SECTOR_BETAS = {
    "Technology": 1.35,
    "Communication Services": 1.20,
    "Consumer Discretionary": 1.25,
    "Financials": 1.10,
    "Industrials": 0.95,
    "Healthcare": 0.75,
    "Consumer Staples": 0.60,
    "Utilities": 0.55,
    "Real Estate": 0.85,
    "Energy": 0.90,
    "Materials": 1.00,
    "Unknown": 1.00,
}

NEGATIVE_KEYWORDS = {"drop", "fall", "crash", "decline", "down", "correction", "bear"}
POSITIVE_KEYWORDS = {"rally", "rise", "surge", "gain", "up", "bull"}


def run_scenario(scenario: str, holdings: dict, market_data: dict) -> dict:
    scenario_lower = scenario.lower()

    match = re.search(r"(\d+(?:\.\d+)?)\s*%", scenario)
    market_move_pct = float(match.group(1)) if match else 10.0

    if any(word in scenario_lower for word in NEGATIVE_KEYWORDS):
        market_move_pct = -market_move_pct
    elif any(word in scenario_lower for word in POSITIVE_KEYWORDS):
        pass  # already positive
    else:
        market_move_pct = -market_move_pct  # default to negative

    positions = []
    total_impact_usd = 0.0
    impact_lines = []

    for ticker, holding in holdings.items():
        ticker_data = market_data.get(ticker)
        if not ticker_data:
            logger.warning("market_data missing for %s — skipping in scenario calculation", ticker)
            continue

        sector = ticker_data.get("sector") or "Unknown"
        beta = SECTOR_BETAS.get(sector, 1.00)
        current_value = holding.get("current_value") or (
            (holding.get("quantity") or 0) * (ticker_data.get("current_price") or 0)
        )

        estimated_move_pct = market_move_pct * beta
        estimated_impact_usd = current_value * (estimated_move_pct / 100)
        total_impact_usd += estimated_impact_usd

        positions.append({
            "ticker": ticker,
            "sector": sector,
            "beta": beta,
            "estimated_move_pct": round(estimated_move_pct, 2),
            "estimated_impact_usd": round(estimated_impact_usd, 2),
            "current_value": round(current_value, 2),
        })

        impact_lines.append(
            f"- {ticker} | Sector: {sector} | Beta: {beta} | "
            f"Est. move: {estimated_move_pct:+.1f}% | "
            f"Est. impact: ${estimated_impact_usd:,.2f} | "
            f"Current value: ${current_value:,.2f}"
        )

    impact_summary = "\n".join(impact_lines)

    prompt = (
        f"Scenario: {scenario}\n\n"
        f"Portfolio impact analysis:\n{impact_summary}\n\n"
        f"Total estimated portfolio impact: ${total_impact_usd:,.2f}\n\n"
        "Please provide a concise scenario analysis covering:\n"
        "1. Overall portfolio impact and which positions are most exposed\n"
        "2. Whether the portfolio's sector mix amplifies or cushions this scenario\n"
        "3. One specific action or consideration the investor should think about given this scenario\n"
        "Keep the response to 3-4 paragraphs. Be direct and specific — reference actual dollar amounts and position names."
    )

    try:
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        analysis = next(
            (block.text for block in response.content if block.type == "text"),
            "No analysis returned.",
        )
        return {
            "scenario": scenario,
            "market_move_pct": market_move_pct,
            "total_impact_usd": round(total_impact_usd, 2),
            "positions": positions,
            "analysis": analysis,
            "status": "success",
        }
    except anthropic.APIError as e:
        logger.error("Anthropic API error during scenario analysis: %s", e)
        return {
            "scenario": scenario,
            "market_move_pct": market_move_pct,
            "total_impact_usd": round(total_impact_usd, 2),
            "positions": positions,
            "analysis": "Analysis unavailable.",
            "status": "error",
        }
    except Exception as e:
        logger.error("Unexpected error during scenario analysis: %s", e)
        return {
            "scenario": scenario,
            "market_move_pct": market_move_pct,
            "total_impact_usd": round(total_impact_usd, 2),
            "positions": positions,
            "analysis": "Analysis unavailable.",
            "status": "error",
        }
