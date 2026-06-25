# Sentinel Unification: Next Steps & Edge Case Handling

Now that Phase 3 (The Unification) architecture has been constructed via `db_handler.py` and `sentinel_orchestrator.py`, we need to wire the final data pathways and handle critical edge cases before deploying to production.

## 1. Immediate Next Steps (Wiring the State)

While the Orchestrator successfully runs the Sentiment LangGraph pipeline concurrently across the 12 ETFs, it is currently running in a vacuum. To fully activate the mathematical core, the following data injections must be wired into `run_pipeline_for_ticker` in `sentinel_orchestrator.py`:

1. **Fetch the Live Macro Shock ($\mathcal{S}_t$)**: Query the `macro_calendar` collection (or an upcoming `macro_state` collection) to pull the most recently computed Surprise Index.
2. **Fetch the Ticker's Beta Vectors**: Read `functions/utils/macro/beta_matrix.json` to extract the `etf_macro_beta` and `ticker_market_beta`.
3. **Inject into LangGraph**: Pass these three values (`macro_shock`, `etf_macro_beta`, `ticker_market_beta`) into the `initial_state` dictionary so the CIO Analyst node can apply the `calculate_effective_sentiment` formula from Step 1.

## 2. Edge Case: The "Empty Database" Scenario

Because the system is brand new, the MongoDB collections (`macro_calendar`, `articles`, `sentiment_leaderboard`) are essentially empty. A critical failure vector exists during the **first high-impact macroeconomic event**:

**The Problem:**
When the ForexFactory Calendar Agent wakes up (e.g., Friday 8:35 AM for NFP) and fetches the realized data, it triggers `calculate_macro_surprise(actual, consensus, historical_std)` in the Math Engine. 
However, because we have not seeded the database with back-data, we have no 5-year rolling standard deviation ($\sigma_{\text{historical}}$). 

**The Graceful Math Fallback:**
The `calculate_macro_surprise` function in `formulas.py` is hardcoded to handle this. If `historical_std` is `None` or `0.0`, the system automatically:
- Defaults the `std_denominator` to `1.0`.
- Returns a `warning_flag = True`.
*This ensures the application never crashes due to a Division-By-Zero error.*

**The Permanent Solution (Backfilling via MCP):**
To eliminate the warning flag and activate true quantitative volatility scaling, we must utilize the **Alpha Vantage MCP Server** (as defined in `NEXT_STEPS.md` Step 2). 

Before the first live trading week, you must run an initialization script (e.g., `scripts/backfill_macro_std.py`) that performs the following:
1. Calls the Alpha Vantage MCP to pull 5 years of historical economic data for the "Core 5" events (NFP, CPI, Unemployment, ISM, Fed Funds Rate).
2. Calculates the rolling standard deviation ($\sigma$) for each series.
3. Saves these baseline denominators permanently into a MongoDB `macro_baselines` collection.

Once this backfill is complete, the Calendar Agent will query this collection for the `historical_std` variable every time it triggers the Math Engine.
