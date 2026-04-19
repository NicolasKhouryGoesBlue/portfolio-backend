# Portfolio Backend — CLAUDE.md

## Project Purpose

This is the backend server for a personal portfolio tracker. It is the intelligence and data layer that serves a React frontend running on `http://localhost:5173`. The backend has three distinct responsibilities:

1. **Market data** — fetches live prices and historical OHLCV data from Yahoo Finance via `yfinance`
2. **AI analysis** — sends portfolio context to Claude (via the Anthropic SDK) and returns a natural-language analysis
3. **REST API** — exposes both of the above to the React frontend through clean HTTP endpoints

The backend runs on port 8000. The frontend runs on port 5173. These are the only two processes in the system.

---

## Architecture

FastAPI server (`main.py`) is the entry point and router. It delegates to two modules:

- `data_fetcher.py` — all yfinance calls
- `analyzer.py` — all Anthropic SDK calls

`main.py` itself contains no data-fetching or AI logic. It wires everything together and handles CORS.

---

## Tech Stack

Every package in `requirements.txt` that matters:

| Package | Version | Role |
|---|---|---|
| `fastapi` | 0.136.0 | Web framework; defines all routes and request/response models |
| `uvicorn` | 0.44.0 | ASGI server that runs the FastAPI app |
| `yfinance` | 1.3.0 | Fetches stock prices, fundamentals, and historical data from Yahoo Finance |
| `anthropic` | 0.96.0 | Official Anthropic SDK; used to call `claude-sonnet-4-6` for portfolio analysis |
| `python-dotenv` | 1.2.2 | Loads `.env` into `os.environ` at startup; required for `ANTHROPIC_API_KEY` |
| `pandas` | 3.0.2 | Used internally by yfinance; history DataFrames are iterated in `data_fetcher.py` |
| `numpy` | 2.4.4 | Dependency of pandas/yfinance |
| `pydantic` | 2.13.2 | FastAPI's validation layer; used implicitly |
| `starlette` | 1.0.0 | FastAPI's underlying ASGI toolkit |
| `httpx` | 0.28.1 | HTTP client used by the Anthropic SDK |
| `requests` | 2.33.1 | Used by yfinance internally |
| `curl_cffi` | 0.15.0 | Used by yfinance for TLS fingerprinting to avoid Yahoo rate limits |

Everything else in `requirements.txt` is a transitive dependency.

---

## File Responsibilities

### `main.py`

Server entry point. Responsibilities:
- Calls `load_dotenv()` at startup to load `.env`
- Instantiates the FastAPI `app`
- Configures `CORSMiddleware` to allow requests from `http://localhost:5173` only
- Imports and wires `get_portfolio_data` from `data_fetcher.py` and `analyze_portfolio` from `analyzer.py`
- Defines all five routes (see API Routes below)
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

If any `info` field is missing from Yahoo Finance, it is `None` in the dict. If fetching a ticker raises an exception, that ticker is omitted from the result entirely (logged, not re-raised). The history period is hardcoded to `1y` in this function — it is not configurable by callers. This function is only called by `POST /analyze`.

### `analyzer.py`

The Anthropic SDK layer. Exports one function:

```python
analyze_portfolio(holdings: dict, market_data: dict) -> str
```

**Input:**
- `holdings`: dict of `{ticker: {"quantity": int, "cost_basis": float}}`
- `market_data`: the output of `get_portfolio_data()`

**What it does:**
1. Computes current value, unrealized P&L, and unrealized % for each holding
2. Aggregates sector weights as percentages of total portfolio value
3. Builds a plain-text prompt summarizing all positions with their fundamentals
4. Sends the prompt to `claude-sonnet-4-6` with `max_tokens=1024`

**Prompt structure** asks Claude to analyze:
1. Overall portfolio health
2. Concentration risks
3. 2–3 specific observations about individual positions or patterns

**Returns:** a plain text string (Claude's response). On `anthropic.APIError` or any other exception, returns a human-readable error string — does not raise.

**API key:** read from `os.environ.get("ANTHROPIC_API_KEY")`. Must exist in `.env` before the server starts. The client is instantiated fresh on every call (not a module-level singleton).

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

**Path parameter:** `ticker` — any valid Yahoo Finance ticker symbol

**Query parameter:** `period` (required) — must be one of the exact strings: `1d`, `5d`, `1mo`, `3mo`, `6mo`, `1y`, `5y`, `max`

These strings are passed directly to `yf.Ticker().history(period=period, interval="1d")` without modification.

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

### `POST /analyze`

Runs the full portfolio analysis pipeline: fetches market data for all tickers, then calls Claude.

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

**Success response (200):**
```json
{
  "analysis": "Plain text analysis from Claude...",
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
Note: this endpoint returns HTTP 200 even on error — the error is in the `status` field.

---

## yfinance Specifics

### Valid period strings for `/history/{ticker}`

```
1d  5d  1mo  3mo  6mo  1y  5y  max
```

These are the only values the endpoint accepts. They are passed verbatim to yfinance.

### Performance warning: `period=max`

`GET /history/{ticker}?period=max` can take **45–60 seconds** to respond. This is normal — Yahoo Finance is returning decades of daily data. It is not a timeout or a bug. Do not add a shorter timeout on either the server or the client for this case.

### Known issue: `period=1d`

`period=1d` currently returns intraday data (minute-resolution candles) rather than a single daily close. The response format differs from all other periods — `history` rows will have intraday timestamps rather than date-only strings. This is a known deferred issue. Do not attempt to fix it by changing the `interval` parameter without verifying the full impact on the frontend.

---

## Anthropic SDK Wiring

- **Key source:** `ANTHROPIC_API_KEY` environment variable, loaded from `.env` via `python-dotenv`
- **Model:** `claude-sonnet-4-6`
- **Max tokens:** `1024`
- **Client:** instantiated per-call inside `analyze_portfolio()` as `anthropic.Anthropic(api_key=...)`
- **Call style:** `client.messages.create(...)` with a single user message containing the full portfolio prompt

If `ANTHROPIC_API_KEY` is missing or invalid, `analyze_portfolio()` catches the `anthropic.APIError` and returns an error string. The server does not crash.

### Billing

The Anthropic API (`console.anthropic.com`) is billed separately from Claude Pro (`claude.ai`). Each `/analyze` call costs approximately **$0.01**. If the API returns a billing error, generate a fresh key from the Anthropic console after confirming credits are loaded. Do not troubleshoot the old key — replace it.

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

Must exist at the project root with at minimum:
```
ANTHROPIC_API_KEY=sk-ant-...
```

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

The `/docs` Swagger UI auto-populates a `{}` wrapper in the request body field for `POST /analyze`. **Always clear the field completely** before pasting your JSON. If you leave the pre-filled `{}` and paste inside it, the request will be malformed. This wastes time if forgotten.

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

1. **`period=1d` intraday mismatch** — `/history/{ticker}?period=1d` returns intraday minute candles from yfinance instead of a single daily close. The date format in the response differs from all other periods. Deferred.

2. **Benchmark Comparison uses manual input** — the React frontend's Benchmark Comparison section currently accepts manual user input rather than fetching `^GSPC` live. The backend could trivially support this via `GET /history/%5EGSPC?period=1y` (URL-encoded `^GSPC`). Not yet wired up.
