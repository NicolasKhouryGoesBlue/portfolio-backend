import logging

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from analyzer import analyze_portfolio
from data_fetcher import get_portfolio_data

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


@app.post("/analyze")
def analyze(data: dict):
    try:
        tickers: list[str] = data.get("tickers", [])
        holdings: dict = data.get("holdings", {})

        market_data = get_portfolio_data(tickers)
        analysis = analyze_portfolio(holdings, market_data)

        return {"analysis": analysis, "status": "success"}
    except Exception as e:
        logger.error("Error in /analyze: %s", e)
        return {"analysis": str(e), "status": "error"}