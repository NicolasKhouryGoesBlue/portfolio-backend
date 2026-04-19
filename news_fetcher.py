"""
news_fetcher.py

Fetches recent news headlines for a stock ticker from the newsapi.org API.
Depends on: NEWSAPI_KEY in .env, the requests library, and python-dotenv.
"""

import logging
import os
from datetime import date, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

NEWSAPI_EVERYTHING_URL = "https://newsapi.org/v2/everything"


def get_news_for_ticker(ticker: str, company_name: str = None) -> list[str]:
    api_key = os.environ.get("NEWSAPI_KEY")
    if not api_key:
        logger.warning("NEWSAPI_KEY is missing or blank — skipping news fetch")
        return []

    query = company_name if company_name else ticker
    from_date = (date.today() - timedelta(days=7)).isoformat()

    params = {
        "q": query,
        "from": from_date,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 5,
        "apiKey": api_key,
    }

    try:
        # /v2/everything searches all sources; broader and more relevant than /v2/top-headlines for financial tickers
        response = requests.get(NEWSAPI_EVERYTHING_URL, params=params, timeout=5)
        response.raise_for_status()
        articles = response.json().get("articles", [])
        return [article["title"] for article in articles if article.get("title")]
    except Exception as e:
        logger.error("Failed to fetch news for %s: %s", ticker, e)
        return []
