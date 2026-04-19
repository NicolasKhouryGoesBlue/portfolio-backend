import logging
import yfinance as yf

logger = logging.getLogger(__name__)


def get_portfolio_data(tickers: list[str]) -> dict:
    result = {}
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            info = stock.info or {}

            history_df = stock.history(period="1y", interval="1d")
            history = {
                str(date.date()): round(close, 2)
                for date, close in history_df["Close"].items()
            } if not history_df.empty else {}

            result[ticker] = {
                "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "history": history,
                "company_name": info.get("longName"),
                "sector": info.get("sector"),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
            }
        except Exception as e:
            logger.error("Failed to fetch data for %s: %s", ticker, e)

    return result
