import logging

import yfinance as yf
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from analyzer import analyze_portfolio
from data_fetcher import get_portfolio_data
from news_fetcher import get_news_for_ticker
from scenario_engine import run_scenario

load_dotenv()

logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "Portfolio backend is running"}


VALID_PERIODS = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "5y", "max"}


@app.get("/prices/{ticker}")
def get_price(ticker: str):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info or {}
        return {
            "ticker": ticker,
            "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "company_name": info.get("longName"),
            "sector": info.get("sector"),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
        }
    except Exception as e:
        logger.error("Failed to fetch price for %s: %s", ticker, e)
        raise HTTPException(status_code=400, detail={"error": str(e), "ticker": ticker})


@app.get("/history/{ticker}")
def get_history(
    ticker: str,
    period: str = Query(...),
):
    if period not in VALID_PERIODS:
        raise HTTPException(
            status_code=400,
            detail={"error": f"Invalid period '{period}'. Valid values: {sorted(VALID_PERIODS)}", "ticker": ticker},
        )
    try:
        stock = yf.Ticker(ticker)
        history_df = stock.history(period=period, interval="1d")
        history = []
        if not history_df.empty:
            history = [
                {"date": str(date.date()), "close": round(float(close), 2)}
                for date, close in history_df["Close"].items()
            ]
        return {"ticker": ticker, "period": period, "history": history}
    except Exception as e:
        logger.error("Failed to fetch history for %s: %s", ticker, e)
        raise HTTPException(status_code=400, detail={"error": str(e), "ticker": ticker})


@app.get("/news/{ticker}")
def get_news(ticker: str, company_name: str = Query(default=None)):
    headlines = get_news_for_ticker(ticker, company_name)
    return {"ticker": ticker, "headlines": headlines}


@app.post("/analyze")
def analyze(data: dict):
    try:
        tickers: list[str] = data.get("tickers", [])
        holdings: dict = data.get("holdings", {})

        market_data = get_portfolio_data(tickers)

        news_data = {}
        for ticker in holdings:
            ticker_market_data = market_data.get(ticker, {})
            company_name = ticker_market_data.get("company_name") if ticker_market_data else None
            news_data[ticker] = get_news_for_ticker(ticker, company_name)

        analysis = analyze_portfolio(holdings, market_data, news_data)

        return {"analysis": analysis, "status": "success"}
    except Exception as e:
        logger.error("Error in /analyze: %s", e)
        return {"analysis": str(e), "status": "error"}


@app.post("/scenario")
def scenario(data: dict):
    scenario_text = data.get("scenario", "")
    if not scenario_text:
        return {"status": "error", "analysis": "No scenario provided."}

    holdings: dict = data.get("holdings", {})
    market_data = get_portfolio_data(list(holdings.keys()))
    return run_scenario(scenario_text, holdings, market_data)