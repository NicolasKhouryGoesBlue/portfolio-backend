"""
chat_engine.py

Handles conversational portfolio Q&A. Takes a user message, conversation history,
and current portfolio context, then calls Claude with a standing system prompt and
returns its reply as a plain string.

Depends on: ANTHROPIC_API_KEY in .env, the anthropic library, and python-dotenv.
"""

import logging
import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def run_chat(message: str, conversation_history: list, holdings: dict, market_data: dict) -> str:
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

        line = (
            f"- {ticker} ({data.get('company_name') or ticker}): "
            f"{quantity} shares @ ${current_price:.2f} = ${current_value:,.2f} | "
            f"Cost basis: ${cost_basis:.2f}/share | "
            f"Unrealized P&L: ${unrealized_gain:,.2f} ({unrealized_pct:.1f}%) | "
            f"Sector: {sector}"
        )
        if data.get("pe_ratio") is not None:
            line += f" | P/E: {data.get('pe_ratio')}"
        if data.get("market_cap") is not None:
            line += f" | Market Cap: {data.get('market_cap')}"
        portfolio_lines.append(line)

    sector_weights = {
        s: f"{(v / total_value * 100):.1f}%" for s, v in sector_values.items()
    } if total_value else {}

    system_prompt = (
        "You are a personal portfolio advisor with access to the user's complete, up-to-date portfolio data. "
        "Use the portfolio information below to answer questions accurately and specifically.\n\n"
        f"Portfolio total value: ${total_value:,.2f}\n\n"
        f"Holdings:\n" + "\n".join(portfolio_lines) + "\n\n"
        f"Sector allocation: {sector_weights}\n\n"
        "Guidelines for your responses:\n"
        "- Answer conversationally and concisely. Do not produce long structured reports unless the user explicitly asks for one.\n"
        "- Reference specific positions, dollar amounts, and percentages from the data above when relevant.\n"
        "- Remember and build on the conversation history from earlier in this session.\n"
        "- Never invent or estimate data that was not provided above. If something is missing, say so."
    )

    messages = list(conversation_history) + [{"role": "user", "content": message}]

    try:
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        )
        return next(
            (block.text for block in response.content if block.type == "text"),
            "No response returned.",
        )
    except anthropic.APIError as e:
        logger.error("Anthropic API error during chat: %s", e)
        return "I encountered an error. Please try again."
    except Exception as e:
        logger.error("Unexpected error during chat: %s", e)
        return "I encountered an error. Please try again."
