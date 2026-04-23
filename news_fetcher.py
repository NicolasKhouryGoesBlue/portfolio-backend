"""
news_fetcher.py

Fetches recent news headlines for a stock ticker from the Finnhub API.
Depends on: FINNHUB_API_KEY in .env, the requests library, and python-dotenv.
"""

import logging
import os
from datetime import date, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

FINNHUB_NEWS_URL = "https://finnhub.io/api/v1/company-news"


def get_news_for_ticker(ticker: str, company_name: str = None) -> list[dict]:
    api_key = os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        logger.warning("FINNHUB_API_KEY is missing or blank — skipping news fetch")
        return []

    to_date = date.today().isoformat()
    from_date = (date.today() - timedelta(days=7)).isoformat()

    params = {
        "symbol": ticker,
        "from": from_date,
        "to": to_date,
        "token": api_key,
    }

    try:
        response = requests.get(FINNHUB_NEWS_URL, params=params, timeout=5)
        response.raise_for_status()
        articles = response.json()
        if not isinstance(articles, list):
            return []
        return [
            {
                "headline": a.get("headline", ""),
                "source": a.get("source", ""),
                "url": a.get("url", ""),
            }
            for a in articles[:5]
            if a.get("headline")
        ]
    except Exception as e:
        logger.error("Failed to fetch news for %s: %s", ticker, e)
        return []
