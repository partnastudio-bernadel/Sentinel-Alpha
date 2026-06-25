# SentinelAlpha: Development Roadmap & Next Steps

> [!NOTE]
> **Last Safe Commit Before Refactoring**: `5eb1b68` ("docs: make links in README relative with sentiment folder as base")

This document outlines the roadmap for the **Sentiment Alpha & Rebalancing Pipeline**, documenting what has been implemented so far and detailing the immediate next steps to link sentiment signals with portfolio governance.

---

## 🏛️ Completed: Step 1 — Mathematical Formulas (Signal Adjustment)

We have successfully implemented and verified the core mathematical equations from Section 2 of the [TRD](file:///d:/PartnaStudio/sentinel/baseline/TRD.md).

* **Module**: [formulas.py](file:///d:/PartnaStudio/sentinel/stack/FinRobot-IntentChain/sentiment/functions/utils/formulas.py)
* **Tests**: [test_formulas.py](file:///d:/PartnaStudio/sentinel/stack/FinRobot-IntentChain/sentiment/functions/utils/test_formulas.py)

### Implemented Functions:
1. **Confidence-Weighted Raw Sentiment ($S_{\text{raw}}$)**:
   $$S_{\text{raw}, j, t} = \frac{\sum_{i=1}^{M_j} s_{i} \cdot c_{i}}{\sum_{i=1}^{M_j} c_{i}}$$
   * *Logic*: Defaults to `0.0` (Neutral) if the article list is empty.
2. **Macro Severity Surprise Index ($\mathcal{S}_t$)**:
   $$\mathcal{S}_t = \omega_{\text{static}} \times \left| \frac{\text{Actual}_t - \text{Consensus}_t}{\sigma_{\text{historical}}} \right|$$
   * *Logic*: Defaults standard deviation to `1.0` if missing or zero (preventing division-by-zero), and triggers a boolean warning flag.
3. **Effective Ticker Sentiment**:
   $$\text{Effective Sentiment}_{j, t} = S_{\text{raw}, j, t} \times (1 + \beta_j \cdot \mathcal{S}_t)$$
   * *Logic*: Scales raw sentiment using default sector betas (e.g. `AAPL`: 1.2, `MSFT`: 1.1) or accepts an optional custom beta.
4. **Portfolio Sentiment**:
   $$\mathcal{S}_{\text{portfolio}, t} = \sum_{j=1}^{n} w_{j, t} \times \text{Effective Sentiment}_{j, t}$$
5. **Portfolio Drift ($L1$-Norm Deviation)**:
   $$\text{Drift}_t = \sum_{j=1}^{n} |w_{\text{actual}, j, t} - w_{\text{target}, j, t}|$$

---

## 🔌 Step 2: Macro Ingestion Strategy (Dual-Source Pipeline)

To fully decouple data harvesting and ensure high-availability calculations for the `calculate_macro_surprise` module, the ingestion layer requires a dual-source infrastructure strategy combining an asynchronous scraper framework with Model Context Protocol (MCP) servers.

### 1. Ingestion Architecture
```
[ForexFactory Web Scraper] ──► Real-Time Core Calendar Feeds (Actual vs. Consensus) ┐
                                                                                   ├──► [FastAPI Data Worker] ──► calculate_macro_surprise()
[Alpha Vantage MCP Server] ──► Historical Multi-Year Baseline (Rolling Std Dev σ)   ┘
```

#### Alpha Vantage MCP Server Integration
* **Strategic Role**: Acts as the primary data engine for long-horizon mathematical context, populating the rolling historical standard deviation ($\sigma_{\text{historical}}$) via standardized payloads.
* **Implementation Details**: Connects as a remote execution layer directly into your FinRobot multi-agent pipeline (https://mcp.alphavantage.co/mcp). This eliminates custom API rate-limiting loops when calculating standard deviations across commodity pricing, currency benchmarks, and multi-year macroeconomic data grids.

#### ForexFactory Scraper Wire-In
* **Strategic Role**: Supplies real-time high-impact macro data releases (Actual, Consensus, and Impact Tier labels) for intraday dynamic tilts.
* **Implementation Details**: Implemented within the FinRobot cluster utilizing asynchronous residential proxy cycling to scrape daily event details. This pulls upcoming high-impact economic calendar streams (e.g., Non-Farm Payrolls, CPI prints) and parses event tiers ("red", "orange", "yellow") directly into the `tier_weights` dictionary.

### 2. Technical Fallback Workflows (TRD Compliance)
To handle data exceptions cleanly, the system maps connections across both sources to avoid structural downtime:
* **Scraper Block Policy**: If the ForexFactory scraper hits a sustained network ban or HTTP 403/429 block lasting over 1 hour, the pipeline logs a `stale_calendar_flag`. It automatically routes requests through the OpenBB Core API or default macro indices to keep operations running smoothly.
* **Missing Denominator Safeguard**: If Alpha Vantage tracking drops out during a live calculation—causing $\sigma_{\text{historical}}$ to return as `None` or `0.0`—the calculation layer triggers the code’s inner catch block:
  ```python
  std_denominator = 1.0
  warning_flag = True
  ```
  This zeroes out custom scaling parameters cleanly and falls back directly to the core baseline portfolio allocation ($w_t = w^{\text{base}}_t$), preventing application crashes.

### 3. Next Engineering Sprint Milestones
* **Expose Ingestion Endpoints**: Create dedicated endpoints within the database configuration (`POST /v1/ingest/macro-calendar`) to wire real-time text arrays directly into `calculate_macro_surprise`.
* **Setup Redis TTL Caching**: Implement active caching on computed surprise metrics within Redis, utilizing dynamic Time-To-Live (TTL) horizons tailored around scheduled global release calendars to minimize processing overhead.

---

## 🏛️ Completed: Step 2.5 — Connect Ingestion Branches to SentinelAlpha Mathematical Core

We have successfully integrated the **Macro Ingestion** and **News Sentiment** branches into the **SentinelAlpha Mathematical Core** formulas.

* **Modules**: 
  * [formulas.py](file:///d:/PartnaStudio/sentinel/sentiment/functions/utils/math/formulas.py) (Math Engine)
  * [macro_scheduler.py](file:///d:/PartnaStudio/sentinel/sentiment/scripts/macro_scheduler.py) (APScheduler Agent)
  * [beta_matrix.json](file:///d:/PartnaStudio/sentinel/sentiment/functions/utils/macro/beta_matrix.json) (Beta Config)
  * [sentinel_orchestrator.py](file:///d:/PartnaStudio/sentinel/sentiment/scripts/sentinel_orchestrator.py) (Orchestration Layer)
* **Tests**: [test_formulas.py](file:///d:/PartnaStudio/sentinel/sentiment/functions/utils/math/test_formulas.py) (if applicable)
* **Reference**: [testing.md](file:///d:/PartnaStudio/sentinel/sentiment/docs/Technical%20Reference/testing.md)

### Implemented Architecture:
1. **The ForexFactory Calendar Agent (`macro_scheduler.py`)**:
   * Run-time agent executing weekly on Sundays at 17:00 EST to scrape the weekly event calendar.
   * Isolates the "Core 5" USD events (NFP, CPI, Unemployment, ISM, FOMC) and schedules background triggers 5 minutes post-release.
   * Implements a "Wake Up" fallback loop with a 300-second sleep and retry cycle to capture realized values.
2. **The Macro Shock Math Engine (`formulas.py`)**:
   * **Z-Score Calculation**: Replaced raw simulated variables with standardized surprise math: `(Actual - Consensus) / StdDev`.
   * **Asymmetric Volatility**: Applied a `1.5x` structural coefficient penalty for negative surprises.
   * **Exponential Decay**: Modeled a 90-day time decay via `math.exp(-0.0077 * t)` to reflect market memory limitations.
3. **The 12-Asset Beta Matrix (`beta_matrix.json`)**:
   * Defines macro sensitivity betas for the 11 GICS sector ETFs + QQQ.
   * Separates sensitivity vectors between "Inflation/Rates" and "Growth/Activity" to properly scale sectors (e.g., QQQ/XLK).
4. **Individual Ticker Scalar Inheritance**:
   * Scales a ticker's effective sentiment using parent sector ETF beta and standard market beta: `AAPL Macro Beta = XLK_Beta * AAPL_Market_Beta`.
5. **Sentinel Orchestrator (`sentinel_orchestrator.py`)**:
   * Unified interface running background ETF sweeps. Protects downstream endpoints against `429 Too Many Requests` API failures using an `asyncio.Semaphore(2)` concurrency limit.
6. **Edge Case Defenses**:
   * Fallback to a standard deviation of `1.0` and warning flags during cold-start phases when historical standard deviations are missing.

---

## 🏛️ Completed: Step 3 — Establish the Storage Layer (MongoDB)

We have established the database infrastructure required to persist and serve data dynamically to our frontend interface.

* **Module**: [db_handler.py](file:///d:/PartnaStudio/sentinel/sentiment/functions/utils/db/db_handler.py)
* **Configuration**: [connect.py](file:///d:/PartnaStudio/sentinel/sentiment/functions/utils/db/connect.py)

### Implemented Architecture:
1. **Database Schema & Collections**:
   * Configured and seeded the `core_entities` collection with primary ETFs.
   * Created and configured the `articles` and `sentiment_leaderboard` collections.
2. **Post-Processing Database Handler (`db_handler.py`)**:
   * A Python connector layer that catches the `SentimentState` output dictionary returned by the LangGraph flow.
   * Performs dynamic MongoDB upserts (`$set` and `$push`) to maintain full historical timeseries scores in the leaderboard natively.
3. **UI Pipeline**:
   * Allows the Streamlit UI to query the MongoDB collections in real-time for sentiment indicators and economic schedules without blocking on heavy LLM reasoning runs.

---

## 🔮 Step 4: Portfolio Optimization & FinRL-X Rebalancing Suggester

With the data engine and storage layers fully complete, the next phase is building the reinforcement-learning-driven portfolio weight suggester.

### Immediate Action Items:
1. **Setup RL Gym Environment (`suggester/env.py`)**:
   * **State Space**: Current portfolio weights ($w_{\text{actual}}$), ticker cash, `Effective Sentiment` timeseries ($\text{Effective Sentiment}_{j, t}$), and calculated portfolio drift.
   * **Action Space**: Target weight tilts ($\Delta w_t$) for portfolio constituents.
2. **Implement Custom Reward Function ($\mathcal{R}_t$)**:
   * Define reward to maximize information ratio against benchmark:
     $$\mathcal{R}_t = (R_{p, t} - R_{b, t}) - \lambda \left( \sum_{j=1}^{n} |w_{j, t} - w_{j, t-1}| \right) - \psi \cdot \mathcal{P}_{\text{slippage}}$$
   * Add a configurable turnover penalty ($\lambda$) and liquidity slippage penalty ($\psi$) to prevent excessive/expensive rebalancing.
3. **Train RL Agent (PPO/DDPG)**:
   * Train models on historical state transitions to learn robust hedging/rebalancing behaviors.
4. **Integrate with IntentCore Validation Gateway**:
   * Connect the output weights ($\mathbf{W}_{\text{proposed}}$) to the IntentCore Gateway `POST /v1/validate-weights` endpoint.
   * Enforce a hard 15% drift ceiling, auto-routing overrides to the PM queue.

---


