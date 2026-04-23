# Portfolio Backend — CLAUDE.md

> **V3 complete.** Phases 9–12 have shipped: conversational chat (`/chat`), Finnhub news (`/news/{ticker}`), scenario stress-test (`/scenario`), and V3 polish. This document reflects the current state of every source file.

---

## Project Purpose

This is the backend server for a personal portfolio tracker. It is the intelligence and data layer that serves a React frontend running on `http://localhost:5173`. The backend has four distinct responsibilities:

1. **Market data** — fetches live prices and historical OHLCV data from Yahoo Finance via `yfinance`
2. **News** — fetches recent headlines per ticker from Finnhub via the `requests` library
3. **AI analysis** — sends portfolio context to Claude (via the Anthropic SDK) and returns structured analysis, scenario impact, or conversational chat
4. **REST API** — exposes all of the above through clean HTTP endpoints

The backend runs on port 8000. The frontend runs on port 5173. These are the only two processes in the system.

---

## Architecture

FastAPI server (`main.py`) is the entry point and router. It delegates to five modules:

- `data_fetcher.py` — all yfinance calls
- `analyzer.py` — portfolio analysis via Anthropic SDK
- `news_fetcher.py` — Finnhub news headlines per ticker
- `chat_engine.py` — multi-turn conversational portfolio Q&A via Anthropic SDK
- `scenario_engine.py` — sector-beta impact math + Claude narrative for stress-test scenarios

`main.py` itself contains no data-fetching or AI logic. It wires everything together and handles CORS.

---

## Tech Stack

Every package in `requirements.txt` that matters:

| Package | Version | Role |
|---|---|---|
| `fastapi` | 0.136.0 | Web framework; defines all routes and request/response models |
| `uvicorn` | 0.44.0 | ASGI server that runs the FastAPI app |
| `yfinance` | 1.3.0 | Fetches stock prices, fundamentals, and historical data from Yahoo Finance |
| `anthropic` | 0.96.0 | Official Anthropic SDK; used by `analyzer.py`, `chat_engine.py`, `scenario_engine.py` to call `claude-sonnet-4-6` |
| `requests` | 2.33.1 | Used by `news_fetcher.py` to call the Finnhub REST API |
| `python-dotenv` | 1.2.2 | Loads `.env` into `os.environ` at startup; required for both `ANTHROPIC_API_KEY` and `FINNHUB_API_KEY` |
| `pandas` | 3.0.2 | Used internally by yfinance; history DataFrames are iterated in `data_fetcher.py` |
| `numpy` | 2.4.4 | Dependency of pandas/yfinance |
| `pydantic` | 2.13.2 | FastAPI's validation layer; used implicitly |
| `starlette` | 1.0.0 | FastAPI's underlying ASGI toolkit |
| `httpx` | 0.28.1 | HTTP client used by the Anthropic SDK |
| `curl_cffi` | 0.15.0 | Used by yfinance for TLS fingerprinting to avoid Yahoo rate limits |

Everything else in `requirements.txt` is a transitive dependency.

---

## File Responsibilities

### `main.py`

Server entry point. Responsibilities:
- Calls `load_dotenv()` at startup to load `.env`
- Instantiates the FastAPI `app`
- Configures `CORSMiddleware` to allow requests from `http://localhost:5173` only
- Imports and wires all five backend modules
- Defines all seven routes (see API Routes below)
- Imports `yfinance` directly for the `/prices/{ticker}` and `/history/{ticker}` endpoints

### `data_fetcher.py`

The yfinance data layer. Exports one function:

```python
get_portfolio_data(tickers: list[str]) -> dict
```

For each ticker, calls `yf.Ticker(ticker).info` and `stock.history(period="1y", interval="1d")`. Returns a dict keyed by ticker:

```python
{
  "AAPL": {
    "current_price": 185.20,       # from info["currentPrice"] or info["regularMarketPrice"]
    "history": {                    # dict keyed by "YYYY-MM-DD" string
      "2024-01-02": 185.20,
      ...
    },
    "company_name": "Apple Inc.",  # from info["longName"]
    "sector": "Technology",        # from info["sector"]
    "market_cap": 2900000000000,   # from info["marketCap"]
    "pe_ratio": 28.5,              # from info["trailingPE"]
  }
}
```

If any `info` field is missing from Yahoo Finance, it is `None` in the dict. If fetching a ticker raises an exception, that ticker is omitted from the result entirely (logged, not re-raised). The history period is hardcoded to `1y` — not configurable by callers. This function is called by `POST /analyze`, `POST /scenario`, and `POST /chat`.

### `analyzer.py`

The portfolio analysis module. Exports one function:

```python
analyze_portfolio(holdings: dict, market_data: dict, news_data: dict = None) -> str
```

**Input:**
- `holdings`: dict of `{ticker: {"quantity": int, "cost_basis": float}}`
- `market_data`: the output of `get_portfolio_data()`
- `news_data`: optional dict of `{ticker: [{headline, source, url}]}` — included in the prompt if provided

**What it does:**
1. Computes current value, unrealized P&L, and unrealized % for each holding
2. Aggregates sector weights as percentages of total portfolio value
3. Builds a plain-text prompt with all positions, fundamentals, sector weights, and (if provided) recent news headlines
4. Sends the prompt to `claude-sonnet-4-6` with `max_tokens=4096`

**Prompt format contract:** The prompt instructs Claude to produce a response in a strict format:
```
• [Conclusion 1 — specific takeaway, under 25 words]
• [Conclusion 2 — specific takeaway, under 25 words]
• [Conclusion 3 — specific takeaway, under 25 words]
---FULL ANALYSIS---
[Full multi-section analysis]
```

The frontend (`Analysis.jsx`) splits the response on the literal string `---FULL ANALYSIS---` to separate the 3-bullet summary from the full analysis body. If this divider is absent from the model's response, the frontend falls back to displaying the full text unsplit. Do not change the divider string in either the prompt or the frontend without updating both sides.

**Returns:** a plain text string (Claude's response). On `anthropic.APIError` or any other exception, returns a human-readable error string — does not raise.

**API key:** read from `os.environ.get("ANTHROPIC_API_KEY")`. Client is instantiated per-call, not as a module-level singleton.

### `news_fetcher.py`

The Finnhub news layer. Exports one function:

```python
get_news_for_ticker(ticker: str, company_name: str = None) -> list[dict]
```

Calls the Finnhub `/company-news` REST endpoint for the last 7 days (today minus 7 days to today). Returns up to 5 items, filtered to those with a non-empty headline:

```python
[
  {"headline": "Apple reports record earnings", "source": "Reuters", "url": "https://..."},
  ...
]
```

If `FINNHUB_API_KEY` is missing or blank, logs a warning and returns `[]` immediately — no exception raised. If the HTTP request fails or the response is not a list, also returns `[]`. The `company_name` parameter is accepted but not currently used in the API call (available for future filtering).

**Called by:** `POST /analyze` (once per holding, before Claude call) and `GET /news/{ticker}` (directly).

### `chat_engine.py`

Multi-turn conversational Q&A. Exports one function:

```python
run_chat(message: str, conversation_history: list, holdings: dict, market_data: dict) -> str
```

Builds a standing system prompt containing the user's full portfolio context (total value, per-position breakdown with P&L, sector allocation). Appends the `conversation_history` (prior `[{role, content}]` turns) plus the new user message, then calls `claude-sonnet-4-6` with `max_tokens=1024` using the `system=` parameter.

The portfolio context is rebuilt fresh on every call from live `market_data` — it is not cached between turns. The frontend is responsible for passing the full `conversation_history` on each request.

On any error, returns the string `"I encountered an error. Please try again."` — does not raise.

### `scenario_engine.py`

Portfolio stress-test engine. Exports one function:

```python
run_scenario(scenario: str, holdings: dict, market_data: dict) -> dict
```

**What it does:**

1. **Extracts market move %** from the scenario string using `re.search(r"(\d+(?:\.\d+)?)\s*%", scenario)`. If no percentage is found, defaults to 10%.
2. **Determines direction** by scanning for keywords:
   - Negative keywords (`drop`, `fall`, `crash`, `decline`, `down`, `correction`, `bear`) → move is negative
   - Positive keywords (`rally`, `rise`, `surge`, `gain`, `up`, `bull`) → move is positive
   - No keywords → defaults to negative
3. **Applies sector betas** from the hardcoded `SECTOR_BETAS` dict:

   | Sector | Beta |
   |---|---|
   | Technology | 1.35 |
   | Communication Services | 1.20 |
   | Consumer Discretionary | 1.25 |
   | Financials | 1.10 |
   | Industrials | 0.95 |
   | Healthcare | 0.75 |
   | Consumer Staples | 0.60 |
   | Utilities | 0.55 |
   | Real Estate | 0.85 |
   | Energy | 0.90 |
   | Materials | 1.00 |
   | Unknown | 1.00 |

   `estimated_move_pct = market_move_pct * beta`
   `estimated_impact_usd = current_value * (estimated_move_pct / 100)`

4. **Calls Claude** (`claude-sonnet-4-6`, `max_tokens=1024`) with the computed per-position impact table and asks for a 3–4 paragraph narrative covering: overall impact, whether the sector mix amplifies or cushions the scenario, and one specific investor consideration.

**Returns:**
```python
{
  "scenario": "original scenario string",
  "market_move_pct": -10.0,          # signed float
  "total_impact_usd": -45230.50,     # signed float
  "positions": [
    {
      "ticker": "AAPL",
      "sector": "Technology",
      "beta": 1.35,
      "estimated_move_pct": -13.5,
      "estimated_impact_usd": -18225.00,
      "current_value": 135000.00,
    },
    ...
  ],
  "analysis": "Claude narrative...",
  "status": "success" | "error",
}
```

On any error, returns the same shape with `"status": "error"` and `"analysis": "Analysis unavailable."` — does not raise.

---

## API Routes

### `GET /`
Health check.

**Response:**
```json
{"status": "Portfolio backend is running"}
```

---

### `GET /prices/{ticker}`

Fetches current price and key fundamentals for a single ticker directly via `yf.Ticker().info`.

**Path parameter:** `ticker` — any valid Yahoo Finance ticker symbol (e.g. `AAPL`, `^GSPC`)

**Success response (200):**
```json
{
  "ticker": "AAPL",
  "current_price": 185.20,
  "company_name": "Apple Inc.",
  "sector": "Technology",
  "market_cap": 2900000000000,
  "pe_ratio": 28.5
}
```
Any field that Yahoo Finance does not return is `null`.

**Error response (400):**
```json
{"error": "descriptive message", "ticker": "AAPL"}
```

---

### `GET /history/{ticker}?period={period}`

Fetches daily closing price history for a single ticker.

**Path parameter:** `ticker` — any valid Yahoo Finance ticker symbol. `^GSPC` must be URL-encoded as `%5EGSPC` by the caller.

**Query parameter:** `period` (required) — must be one of: `1d`, `5d`, `1mo`, `3mo`, `6mo`, `1y`, `5y`, `max`

**Success response (200):**
```json
{
  "ticker": "AAPL",
  "period": "1y",
  "history": [
    {"date": "2024-01-02", "close": 185.20},
    {"date": "2024-01-03", "close": 184.10}
  ]
}
```
Dates are `YYYY-MM-DD` strings. If yfinance returns no rows, `history` is `[]`.

**Error response (400):**
```json
{"error": "descriptive message", "ticker": "AAPL"}
```
An invalid `period` value also returns 400.

---

### `GET /news/{ticker}?company_name={company_name}`

Fetches recent headlines for a single ticker from Finnhub.

**Path parameter:** `ticker` — stock ticker symbol (e.g. `AAPL`)

**Query parameter:** `company_name` (optional) — accepted but not currently used in the Finnhub API call

**Success response (200):**
```json
{
  "ticker": "AAPL",
  "headlines": [
    {"headline": "Apple hits record high", "source": "Reuters", "url": "https://..."},
    {"headline": "iPhone sales beat estimates", "source": "Bloomberg", "url": "https://..."}
  ]
}
```
Returns up to 5 items. If `FINNHUB_API_KEY` is missing or the request fails, `headlines` is `[]` — never an error status.

---

### `POST /analyze`

Runs the full portfolio analysis pipeline: fetches market data and news for all tickers, then calls Claude.

**Request body:**
```json
{
  "tickers": ["AAPL", "MSFT"],
  "holdings": {
    "AAPL": {"quantity": 10, "cost_basis": 150.00},
    "MSFT": {"quantity": 5, "cost_basis": 280.00}
  }
}
```

**Pipeline:**
1. Calls `get_portfolio_data(tickers)` — live prices + 1y history
2. Calls `get_news_for_ticker(ticker, company_name)` for each holding — Finnhub headlines
3. Calls `analyze_portfolio(holdings, market_data, news_data)` — Claude with `max_tokens=4096`

**Success response (200):**
```json
{
  "analysis": "• Conclusion 1\n• Conclusion 2\n• Conclusion 3\n---FULL ANALYSIS---\nFull analysis body...",
  "status": "success"
}
```

**Error response (200 with error status):**
```json
{
  "analysis": "error message string",
  "status": "error"
}
```
This endpoint always returns HTTP 200 — errors are signaled via the `status` field.

---

### `POST /scenario`

Stress-tests the portfolio against a plain-English scenario description.

**Request body:**
```json
{
  "scenario": "The market drops 20% due to a recession",
  "holdings": {
    "AAPL": {"quantity": 10, "cost_basis": 150.00}
  }
}
```

`market_data` does **not** need to be sent — the backend calls `get_portfolio_data()` itself.

**Success response (200):**
```json
{
  "scenario": "The market drops 20% due to a recession",
  "market_move_pct": -20.0,
  "total_impact_usd": -37800.00,
  "positions": [
    {
      "ticker": "AAPL",
      "sector": "Technology",
      "beta": 1.35,
      "estimated_move_pct": -27.0,
      "estimated_impact_usd": -37800.00,
      "current_value": 140000.00
    }
  ],
  "analysis": "Claude narrative...",
  "status": "success"
}
```

On error: same shape, `"status": "error"`, `"analysis": "Analysis unavailable."`.

---

### `POST /chat`

Sends a user message to Claude with full portfolio context and conversation history.

**Request body:**
```json
{
  "message": "Which of my positions has the most concentration risk?",
  "conversation_history": [
    {"role": "user", "content": "What's my total portfolio value?"},
    {"role": "assistant", "content": "Your portfolio is currently worth $142,300."}
  ],
  "holdings": {
    "AAPL": {"quantity": 10, "cost_basis": 150.00}
  }
}
```

`market_data` does **not** need to be sent — the backend calls `get_portfolio_data()` itself. `conversation_history` may be `[]` for the first turn.

**Success response (200):**
```json
{
  "response": "Claude's reply...",
  "status": "success"
}
```

**Error response (200):**
```json
{
  "response": "I encountered an error. Please try again.",
  "status": "error"
}
```

---

## yfinance Specifics

### Valid period strings for `/history/{ticker}`

```
1d  5d  1mo  3mo  6mo  1y  5y  max
```

These are the only values the endpoint accepts. Passed verbatim to yfinance.

### Performance warning: `period=max`

`GET /history/{ticker}?period=max` can take **45–60 seconds** to respond. Normal — Yahoo Finance is returning decades of daily data. Do not add a shorter timeout on the server or client for this case.

### Known issue: `period=1d`

`period=1d` currently returns intraday data (minute-resolution candles) rather than a single daily close. The date format in the response rows differs from all other periods. Deferred to V4. Do not attempt to fix by changing the `interval` parameter without verifying the full impact on the frontend.

---

## Anthropic SDK Wiring

All three AI modules (`analyzer.py`, `chat_engine.py`, `scenario_engine.py`) follow the same pattern:
- **Key source:** `ANTHROPIC_API_KEY` from `.env` via `python-dotenv`
- **Model:** `claude-sonnet-4-6`
- **Client:** instantiated per-call as `anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))` — not a module-level singleton
- **Call style:** `client.messages.create(...)`

**Max tokens per endpoint:**
| Endpoint | max_tokens |
|---|---|
| `/analyze` | 4096 |
| `/chat` | 1024 |
| `/scenario` | 1024 |

If `ANTHROPIC_API_KEY` is missing or invalid, all three modules catch `anthropic.APIError` and return a human-readable error string. The server does not crash.

### Billing

The Anthropic API (`console.anthropic.com`) is billed separately from Claude Pro (`claude.ai`). Each `/analyze` call costs approximately **$0.01–$0.03** (higher than before due to `max_tokens=4096` and news context). `/chat` and `/scenario` are cheaper (~$0.01 each). If the API returns a billing error, generate a fresh key from the Anthropic console after confirming credits are loaded.

---

## Environment Setup

### Virtual environment

The venv lives at `venv/` inside the project root. It must be activated before running the server or installing packages.

**Activation:**
```bash
source venv/bin/activate
```

**Confirmation:** `(venv)` appears at the start of the terminal prompt.

**Python version:** Use `python3.11` on this machine — not `python` or `python3`.

### `.env` file

Must exist at the project root. Required keys:
```
ANTHROPIC_API_KEY=sk-ant-...
FINNHUB_API_KEY=...
```

Both keys are required for full functionality:
- Without `ANTHROPIC_API_KEY`: `/analyze`, `/scenario`, and `/chat` will return error responses
- Without `FINNHUB_API_KEY`: `/news/{ticker}` returns `[]` and `/analyze` proceeds without news context

`.env` is in `.gitignore` and is never pushed to GitHub.

---

## How to Start the Server

```bash
# 1. Navigate to project folder
cd "/Users/nicok/Documents/Claude Code Projects/portfolio-backend"

# 2. Activate the venv
source venv/bin/activate

# 3. Start the server
uvicorn main:app --reload --port 8000
```

**URLs once running:**
- `http://localhost:8000` — health check (`GET /`)
- `http://localhost:8000/docs` — interactive Swagger UI for testing all endpoints

---

## FastAPI /docs Quirk

The `/docs` Swagger UI auto-populates a `{}` wrapper in the request body field for POST endpoints. **Always clear the field completely** before pasting your JSON. If you leave the pre-filled `{}` and paste inside it, the request will be malformed.

---

## CORS Configuration

`CORSMiddleware` in `main.py` allows:
```python
allow_origins=["http://localhost:5173"]
```

If the React frontend moves to a different port, this value must be updated in `main.py`. Only the origin is restricted — methods and headers are `*`.

---

## GitHub Hygiene

**Never pushed:**
- `venv/` — confirmed in `.gitignore`
- `.env` — confirmed in `.gitignore`
- `__pycache__/` — confirmed in `.gitignore`

**Must be kept current:**
- `requirements.txt` — the portable dependency record. After installing any new package, regenerate it:
  ```bash
  pip freeze > requirements.txt
  ```

---

## Known Issues and Deferred Work

1. **`period=1d` intraday mismatch** — `/history/{ticker}?period=1d` returns intraday minute candles from yfinance instead of a single daily close. The date format in the response differs from all other periods. The frontend chart shows nothing on weekends or after market close for this reason. Deferred to V4.

2. **Scenario % extraction is naive** — `scenario_engine.py` uses a simple regex to find the first number followed by `%`. A scenario like "inflation rises 3% causing a 15% market drop" would extract `3` rather than `15`. Deferred.

3. **`news_fetcher.py` `company_name` parameter is unused** — the parameter is accepted (and passed by callers) but not sent to Finnhub. Finnhub's `/company-news` endpoint only accepts a ticker symbol. The parameter exists for potential future use (e.g. filtering headlines by company name). No action needed.

---

## Changelog (vs. pre-Phase-9 version)

**Added:**
- V3 complete notice at top
- Architecture section updated: "two modules" → "five modules"
- `news_fetcher.py` file description (Finnhub, `{headline, source, url}` shape, graceful empty return)
- `chat_engine.py` file description (system prompt pattern, `max_tokens=1024`, conversation history threading)
- `scenario_engine.py` file description (sector-beta table, keyword direction detection, Claude narrative, full response shape)
- Tech stack: added `requests` as direct dep (Finnhub); clarified `anthropic` SDK used by three modules
- `GET /news/{ticker}` endpoint — full request/response documentation; corrected response key to `headlines` (not `news`)
- `POST /scenario` endpoint — full request/response documentation
- `POST /chat` endpoint — full request/response documentation
- `/analyze` pipeline now documents the intermediate news fetch step
- `max_tokens` per-endpoint table; corrected `/analyze` from 1024 → 4096
- `---FULL ANALYSIS---` divider contract documented under `analyzer.py`
- `.env` section: added `FINNHUB_API_KEY`; documented degraded behavior when each key is missing
- Billing note updated for higher `/analyze` token budget
- Known issues: added scenario % extraction caveat; added `company_name` unused note

**Removed:**
- "Benchmark Comparison uses manual input" known issue — resolved in V3 (^GSPC live data now fetched via `/history/%5EGSPC?period=max`)
- References to `NEWSAPI_KEY` — never existed in this codebase
- `analyzer.py` old signature `(holdings, market_data)` — corrected to include `news_data` third arg
- Claim that `max_tokens=1024` in `/analyze` — was wrong; corrected to 4096

**Updated:**
- Architecture diagram
- `analyzer.py` section: prompt format contract, `news_data` param, `max_tokens=4096`
- `main.py` section: "five routes" → "seven routes"
- `data_fetcher.py` section: noted it is now called by three endpoints, not just `/analyze`
