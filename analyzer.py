import logging
import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def analyze_portfolio(holdings: dict, market_data: dict, news_data: dict = None) -> str:
    portfolio_lines = []
    sector_values: dict[str, float] = {}
    total_value = 0.0

    for ticker, holding in holdings.items():
        data = market_data.get(ticker)
        if not data:
            continue

        quantity = holding.get("quantity", 0)
        cost_basis = holding.get("cost_basis", 0)
        current_price = data.get("current_price") or 0

        current_value = quantity * current_price
        total_cost = quantity * cost_basis
        unrealized_gain = current_value - total_cost
        unrealized_pct = (unrealized_gain / total_cost * 100) if total_cost else 0

        total_value += current_value

        sector = data.get("sector") or "Unknown"
        sector_values[sector] = sector_values.get(sector, 0.0) + current_value

        portfolio_lines.append(
            f"- {ticker} ({data.get('company_name') or ticker}): "
            f"{quantity} shares @ ${current_price:.2f} = ${current_value:,.2f} | "
            f"Unrealized P&L: ${unrealized_gain:,.2f} ({unrealized_pct:.1f}%) | "
            f"Sector: {sector} | "
            f"Market Cap: {data.get('market_cap')} | "
            f"P/E: {data.get('pe_ratio')}"
        )

    sector_weights = {
        s: f"{(v / total_value * 100):.1f}%" for s, v in sector_values.items()
    } if total_value else {}

    news_context = ""
    if news_data:
        news_lines = []
        for ticker, headlines in news_data.items():
            if not headlines:
                continue
            news_lines.append(f"{ticker}:")
            for headline in headlines:
                news_lines.append(f"- {headline}")
            news_lines.append("")
        if news_lines:
            news_context = "Recent news headlines (last 7 days):\n\n" + "\n".join(news_lines).rstrip()

    news_instruction = (
        "\n\nPlease factor in the recent news headlines above when assessing each position, "
        "noting any headlines that could affect the investment thesis, sector outlook, or near-term risk "
        "for the holdings. If no headlines are shown for a ticker, do not speculate about news — "
        "only reason about what is provided."
    ) if news_context else ""

    news_block = f"\n\n{news_context}{news_instruction}" if news_context else ""

    prompt = (
        f"Portfolio total value: ${total_value:,.2f}\n\n"
        f"Holdings:\n" + "\n".join(portfolio_lines) + "\n\n"
        f"Sector weights: {sector_weights}"
        f"{news_block}\n\n"
        "Please provide a concise portfolio analysis covering:\n"
        "1. Overall portfolio health\n"
        "2. Concentration risks\n"
        "3. 2-3 specific observations about individual positions or patterns"
    )

    try:
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return next(
            (block.text for block in response.content if block.type == "text"),
            "No analysis returned.",
        )
    except anthropic.APIError as e:
        logger.error("Anthropic API error during portfolio analysis: %s", e)
        return f"Portfolio analysis unavailable: API error — {e}"
    except Exception as e:
        logger.error("Unexpected error during portfolio analysis: %s", e)
        return f"Portfolio analysis unavailable: {e}"
