# 📂 Sentiment Analysis Module: Documentation & Reference Catalog

Welcome to the Sentiment Analysis module! This catalog serves as the central **Table of Contents (TOC)** and directory map for all documentation, tutorials, modular functions, APIs, prompts, and schema contracts available in this workspace.

---

## 🗺️ Workspace Map & Directory Structure

```
sentiment/
├── docs/                    # Centralized system documentation catalog
│   ├── Strategic Core/      # Core designs, roadmaps, and database stats
│   │   ├── architecture.md
│   │   ├── coordination.md
│   │   ├── database.md
│   │   └── roadmap.md
│   ├── Coverage/            # Provider matrices and model capability analysis
│   │   ├── models.md
│   │   └── providers.md
│   ├── Technical Reference/ # Technical specs, standards, and dynamic flow diagrams
│   │   ├── architecture/
│   │   │   ├── macro.md
│   │   │   └── sentiment.md
│   │   ├── graphs/
│   │   │   ├── macro.md
│   │   │   └── news.md
│   │   ├── standards/
│   │   │   ├── docstrings.md
│   │   │   └── prompts.md
│   │   └── testing.md
│   ├── Workarounds/         # Tactical troubleshooting guides and offline scripts
│   │   ├── mcp.md
│   │   ├── transcripts_free.md
│   │   └── transcripts_offline.md
│   └── README.md            # This file
├── functions/               # Core codebase functions
│   ├── aggregator/          # News aggregation logic
│   ├── providers/           # API integrations for news platforms
│   ├── tools/               # Deterministic data/agent tools (edgar_tools, transcript_tools)
│   └── utils/               # Math, config, scheduler, and compliance logging utilities
├── logs/                    # Audit logs (scheduler_audit.jsonl, compliance_audit.jsonl)
├── scripts/                 # CLI scripts (news_sentiment_cli, macro_ingestion_cli)
└── tutorials/               # Step-by-step notebook guides and evolution
```

---

## 📄 Architectural Guides & Documentation

| Document File | Purpose / Description |
| :--- | :--- |
| [architecture.md](docs/Strategic%20Core/architecture.md) | **Updated System Design**: Details the full single-agent direct tool-calling architecture, the Smart Scheduler fail-safe layer, the Unstructured Reading Workers Layer, and the Thesis-CoT Audit Scribe compliance integration. |
| [coordination.md](docs/Strategic%20Core/coordination.md) | **Pipeline Coordination**: Details background orchestration loops, ad-hoc CLI usage, and chatbot interactions. |
| [roadmap.md](docs/Strategic%20Core/roadmap.md) | **Development Roadmap**: Details milestones, macro surprise ingestion API endpoints, Redis caching, SQLite storage layer, and the FinRL-X portfolio optimization Suggester. |
| [database.md](docs/Strategic%20Core/database.md) | **Database & Storage Growth**: Executive summary of document counts, footprint size, and data velocities. |
| [sentiment.md](docs/Technical%20Reference/architecture/sentiment.md) | **Core System Design**: Explains the 3-layer system layout, mathematical scoring equations, database schemas, vector caching, and websocket contracts. |
| [macro.md](docs/Technical%20Reference/architecture/macro.md) | **Macro Ingestion Design**: Outlines the economic surprise index mathematical formulation, model interactions, data contracts, and fallback boundaries. |
| [news.md](docs/Technical%20Reference/graphs/news.md) | **News Sentiment Flow Diagram**: Visualizes the LangGraph flow representing news ingestion, cache checking, sentiment scoring, and CIO analyst report aggregation. |
| [macro.md](docs/Technical%20Reference/graphs/macro.md) | **Macro Ingestion Flow Diagram**: Visualizes the LangGraph flow for the macro indicators ingestion, economic surprise calculation, and final report compilation. |
| [testing.md](docs/Technical%20Reference/testing.md) | **Edge Case Handling**: Outlines calibration strategies, standard deviation backfills, and mathematical division safeguards. |
| [docstrings.md](docs/Technical%20Reference/standards/docstrings.md) | **Docstring Guidelines & Standards**: Establishes strict rules for all Python functions and tools used by FinRobot agents, enforcing selection criteria, type hints, and error payloads. |
| [prompts.md](docs/Technical%20Reference/standards/prompts.md) | **Prompt Engineering Standards (CARE)**: Outlines guidelines and standards for structuring agent system prompt templates using the CARE framework and decoupled schema architecture. |
| [providers.md](docs/Coverage/providers.md) | **API & Scraping Status**: Outlines support details for OpenBB platform news connectors, status matrix of the 11 integrated providers, and headless browser scraping results. |
| [models.md](docs/Coverage/models.md) | **Model Testing & Optimization**: Details capabilities and test outcomes for Minimax, Llama-3.1, Mistral, Qwen, Kimi, and DeepSeek under ReAct orchestration. |
| [mcp.md](docs/Workarounds/mcp.md) | **MCP Integration Limitations**: Summarizes design limitations and mitigations for Alpha Vantage, ForexFactory, and AutoGen nested chat response swallowing. |
| [transcripts_free.md](docs/Workarounds/transcripts_free.md) | **Free Transcript Pulls**: Details Motley Fool scraper patterns and local Whisper transcription configurations. |
| [transcripts_offline.md](docs/Workarounds/transcripts_offline.md) | **Offline Backtesting**: Explains offline dataset integration via Kaggle or Hugging Face. |

---

## 🚀 Tutorials: Agent & Refactoring Evolution

We transitioned from a rigid, monolithic notebook pipeline into a highly modular, decoupled, and agentic delegation architecture, and finally into a fast and reliable single-agent tool-calling framework:

### 1. [llama3_aapl_news.ipynb](tutorials/llama3_aapl_news.ipynb) — Monolithic Baseline (Tested ✅)
* **Purpose**: Fetches, cleans, and scores AAPL news articles inline.
* **Limitations**: Highly redundant inline cells, manual regex response sanitization, and lack of separation between concerns.

### 2. [llama3_news.ipynb](tutorials/llama3_news.ipynb) — Modular Refactoring (Tested ✅)
* **Purpose**: Decouples the core pipeline functions from execution notebooks.
* **Key Enhancements**: Moving standard tasks to helper files (e.g., config generators, scrapers, database loaders) and wrapping them in standard agent factory creation methods.

### 3. [llama3_news_delegation.ipynb](tutorials/llama3_news_delegation.ipynb) — Agent-to-Agent Nested Chat (Archived)
* **Purpose**: Setup AutoGen-based multi-agent coordination with transparent chunk batching.
* **Key Enhancements**: Used a User Proxy to delegate to a Senior Sentiment Analyst (CIO) Agent, which automatically delegated to a Sentiment Scorer Agent in batches. This has now been simplified to direct Python-orchestrated tool-calling for significantly faster execution and lower latency.

### 4. [macro_ingestion_delegation.ipynb](tutorials/macro_ingestion_delegation.ipynb) — Macro Ingestion & Multi-Agent Calculation (Archived)
* **Purpose**: Simulated macro indicators ingestion using MCP clients.
* **Key Enhancements**: Standardized shock index calculation. This has also been upgraded to a single-agent orchestrator with a deterministic `MacroScheduler` middleware layer to prevent rate limits and timeouts from failing the process.

---

## 💻 CLI Scripts & Utilities

### 1. [news_sentiment_cli.py](scripts/news_sentiment_cli.py)
* **Purpose**: Single-agent headline scoring, SEC risk extraction, and FMP earnings transcript tension calculations.
* **Usage**: `python scripts/news_sentiment_cli.py --ticker MSFT --limit 10`

### 2. [macro_ingestion_cli.py](scripts/macro_ingestion_cli.py)
* **Purpose**: Single-agent quantitative economic surprise calculations.
* **Usage**: `python scripts/macro_ingestion_cli.py --event "CPI m/m" --indicator CPI`

### 3. [macro_scheduler.py](scripts/macro_scheduler.py)
* **Purpose**: Weekly calendar scraper, hourly realized data sweep, and APScheduler background loop.
* **Usage**:
  * Daemon: `python scripts/macro_scheduler.py`
  * Fetch Calendar: `python scripts/macro_scheduler.py --fetch`
  * Sweep Realized: `python scripts/macro_scheduler.py --sweep`

### 4. [sentinel_orchestrator.py](scripts/sentinel_orchestrator.py)
* **Purpose**: Background orchestrator running concurrent LangGraph sweeps across the Core ETF list.
* **Usage**:
  * Single ETF: `python scripts/sentinel_orchestrator.py --ticker XLK`
  * Background Sweep: `python scripts/sentinel_orchestrator.py --background`


---

## 🛠️ Codebase Functions Reference

### 🌐 News Ingestion & Aggregation

#### 📂 Aggregator Component (`functions/aggregator/`)
* **[fetch_aggregate_all_news](functions/aggregator/aggregator.py#L17)**: Consolidates, deduplicates, and standardizes news articles from 11 sources.

#### 📂 Data Provider Endpoints (`functions/providers/`)
* **[fetch_alpha_vantage](functions/providers/alpha_vantage.py#L5)**: Fetches news articles and sentiment metrics from the Alpha Vantage API.
* **[fetch_finviz_scrape](functions/providers/finviz.py#L39)**: Custom BeautifulSoup scraper parsing the public HTML news table on the Finviz page.
* **[fetch_nasdaq_api](functions/providers/nasdaq.py#L4)**: Fetches public news feeds from the Nasdaq JSON API endpoints.
* **[fetch_news_api](functions/providers/news_api.py#L5)**: Fetches news feed items from the official NewsAPI.org service.
* **[fetch_seeking_alpha_rapidapi](functions/providers/seeking_alpha.py#L5)**: Fetches articles using the RapidAPI Tipsters Seeking Alpha API.

### 🔌 Structured Reading Workers & Ingestion Tools
* **[get_cik_by_ticker](functions/tools/edgar_tools.py)**: Resolves ticker symbols to official SEC CIK values using SEC mappings.
* **[get_10k_metadata_by_year](functions/tools/edgar_tools.py)**: Finds the accession numbers and primary documents for 10-K filings.
* **[extract_section_1a](functions/tools/edgar_tools.py)**: Deterministically extracts Item 1A (Risk Factors) from raw SEC text.
* **[extract_section_7](functions/tools/edgar_tools.py)**: Deterministically extracts Item 7 (MD&A) from raw SEC text.
* **[split_transcript](functions/tools/transcript_tools.py)**: Programmatically splits earnings call transcripts into Management Presentation vs. Analyst Q&A.

### 🏛️ Math, Fail-Safe, & Logging Utilities
Located in `functions/utils/`:
* **[calculate_raw_sentiment](functions/utils/formulas.py#L3)**: Computes confidence-weighted average sentiment.
* **[calculate_macro_surprise](functions/utils/formulas.py#L38)**: Evaluates economic surprise scaled by impact tier weights.
* **[calculate_effective_sentiment](functions/utils/formulas.py#L80)**: Adjusts sentiment score using asset beta and macro shocks.
* **[calculate_portfolio_sentiment](functions/utils/formulas.py#L112)**: Aggregates ticker sentiment by portfolio weight.
* **[normalize_weights](functions/utils/formulas.py#L166)**: Normalizes top-K weights to sum to 1.0.
* **[MacroScheduler](functions/utils/scheduler.py)**: Failsafe state-machine wrapper that catches, classifies, and bypasses rate limits/timeouts using deterministic NaN-safe fallback payloads.
* **[MacroSurpriseCalibrationAgent](functions/utils/calibration_agent.py)**: TTL cache wrapper for rolling standard deviation fetches with exponential backoff retries.
* **[log_scheduler_event](functions/utils/audit_logger.py)**: Writes scheduler events and error statuses to `logs/scheduler_audit.jsonl`.
* **[log_compliance_event](functions/utils/compliance_logger.py)**: Logs portfolio weight overrides to `logs/compliance_audit.jsonl`.

---

## 🤖 Agent Creators & Orchestration
* **[create_scorer_agent](functions/agents.py)**: Configures and returns the `Sentiment Scorer Agent` designed to parse individual articles.
* **[create_cio_agent](functions/agents.py)**: Configures and returns the `Senior Sentiment Analyst (CIO) Agent` which aggregates results and formats the final report.
* **[create_textual_inertia_agent](functions/agents.py)**: Kimi-powered agent that evaluates 10-K filing text to compute risk drift.
* **[create_tension_extractor_agent](functions/agents.py)**: Kimi-powered agent that analyzes earnings call transcripts Q&A for executive/analyst tension.
* **[create_scribe_agent](functions/agents.py)**: The `Thesis-CoT Scribe` compliance agent that drafts justifications when portfolio weight adjustments exceed the 15% drift threshold.
