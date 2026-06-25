# 💻 CLI Scripts & Integration Reference Catalog

This directory contains standalone Command Line Interface (CLI) scripts designed for executing agent-based analysis pipelines, calculating metrics, and orchestrating Model Context Protocol (MCP) clients.

Both CLI utilities expose programmatically exportable orchestrator functions, making them ready for integration with background task schedulers (e.g. Celery), API routing layers (e.g. FastAPI), or cron configurations.

---

## 1. 📰 Stock News & Reading Workers Sentiment Analyzer (`news_sentiment_cli.py`)

A single-agent sentiment compilation utility that fetches recent stock news, resolves ETF constituents (fetching up to top-K holdings), scrapes and scores articles in batches, runs deep textual analysis using Unstructured Reading Workers, and executes compliance allocation gateway checks.

### Advanced Capabilities:
* **ETF Decomposition**: When run on an ETF ticker (e.g., `SPY`), it resolves constituents and scores each holding proportionally.
* **Unstructured Reading Workers**: Spawns Kimi-powered (`kimi-k2.6`) cognitive agents:
  * **Textual Inertia Agent**: Extracts and analyzes SEC 10-K filing Risk Factors (Item 1A) to score year-over-year risk drift.
  * **Tension Extractor Agent**: Analyzes earnings call Q&A transcripts from FMP to score corporate evasiveness/analyst tension.
* **Compliance Audit Scribe**: Checks if proposed weight adjustments drift by more than 15% from base weights. If exceeded, it triggers the **Thesis-CoT Scribe** to draft a detailed justification override narrative, which is logged locally to `logs/compliance_audit.jsonl`.

### Command Line Flags:
| Flag | Long Flag | Parameter Type | Default Value | Description |
| :--- | :--- | :--- | :--- | :--- |
| `-t` | `--ticker` | `string` | `"AAPL"` | The stock ticker symbol to retrieve news and analyze sentiment for. |
| `-l` | `--limit` | `integer` | `5` | Maximum number of retrieved articles to batch and score. |
| `-k` | `--holdings` | `integer` | `5` | Number of top ETF holdings to analyze if the ticker is an ETF. |
| `-c` | `--csv` | `string` | `None` | Path to the historical financial sentiment CSV used to build the FAISS vector calibration database. |
| `-e` | `--env` | `string` | `None` | Path to the environment configuration file containing API keys and model parameters. |

### CLI Usage Example:
```bash
# Run sentiment analysis for AAPL fetching and scoring the top 5 articles
python sentiment/scripts/news_sentiment_cli.py --ticker AAPL --limit 5

# Run ETF portfolio sentiment analysis for SPY retrieving the top 3 holdings
python sentiment/scripts/news_sentiment_cli.py --ticker SPY --holdings 3 --limit 2
```

---

## 2. 📈 Macro Economic Ingestion & Surprise Index CLI (`macro_ingestion_cli.py`)

An economic surprise index orchestrator. It queries the local ForexFactory calendar MCP client to harvest scheduled economic releases (Actual vs. Forecast) and calls the remote Alpha Vantage API via the `MacroSurpriseCalibrationAgent` to retrieve historical baseline standard deviations, calculating the standardized shock index $\mathcal{S}_t$.

### Advanced Capabilities:
* **Smart Scheduler Middleware**: Wraps MCP calls inside `MacroScheduler.execute_with_guard()`. If a remote source times out or hits a rate limit (HTTP 429), it classifies the error and gracefully injects a NaN-safe fallback payload instead of crashing the pipeline.
* **Rolling Std Dev TTL Cache**: Uses `MacroSurpriseCalibrationAgent` with an in-memory 1-hour TTL cache and exponential backoff retry logic to handle rate-limited baseline fetches.
* **Audit Trails**: Logs all scheduler actions, response latency, and error states directly to `logs/scheduler_audit.jsonl`.

### Command Line Flags:
| Flag | Long Flag | Parameter Type | Default Value | Description |
| :--- | :--- | :--- | :--- | :--- |
| `-v` | `--event` | `string` | `"CPI m/m"` | Target ForexFactory economic calendar event name to search (case-insensitive substring filter). |
| `-i` | `--indicator` | `string` | `"CPI"` | Macro indicator identifier matching Alpha Vantage API metrics. |
| `-e` | `--env` | `string` | `None` | Path to the environment configuration file containing API keys. |

### CLI Usage Example:
```bash
# Retrieve USD CPI calendar event and baseline indicator values for this month
python sentiment/scripts/macro_ingestion_cli.py --event "CPI m/m" --indicator CPI
```

---

## 🔌 API & Python Import Workflows

Both scripts are architected around clean, decoupled core functions. You can import their execution controllers directly into your backend routing layers without invoking shell subprocesses.

```python
# Import the news sentiment orchestrator
from functions.utils.news.pipeline_orchestrator import run_sentiment_analysis

result = run_sentiment_analysis(ticker="AAPL", limit=5, holdings=5)
print(f"Weighted average sentiment: {result['metrics']['sentiment_score']}")

# Import the macro economic surprise ingestion function
from scripts.macro_ingestion_cli import run_macro_ingestion_single

macro_report = run_macro_ingestion_single(event_name="CPI m/m", indicator_name="CPI")
print(f"Calculated surprise index S_t: {macro_report['metrics']['macro_surprise_score']}")
```
