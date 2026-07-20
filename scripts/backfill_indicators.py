#!/usr/bin/env python3
"""
backfill_indicators.py
----------------------
Standalone backfill script that re-runs the Textual Inertia and Q&A Tension
LLM agents against the SEC filings and earnings call transcripts already stored
in the MongoDBStore, for every ticker that has data in 'sentiment_reports'.

ETF-aware:
  - For ETF tickers (e.g. XLC, XLE, XLK, XLY), the script looks up the
    constituent tickers from 'core_entities' and runs the agents on those
    individual companies (exactly as the live cio_analyst_node does).
  - Constituents are processed ONE AT A TIME (not in parallel) to avoid
    hammering the LLM API rate limits. A configurable delay is inserted
    between each constituent call.
  - Per-constituent scores are averaged to produce a single ETF-level score
    before being stored and back-patched.
  - Single-stock tickers are processed directly.

Each call produces a fresh indicator_snapshots document (time-series insert,
not upsert). The most recent sentiment_reports document for each ticker is
also back-patched with the new scores.

Usage:
  # Dry-run all tickers (no writes)
  python local/scripts/backfill_indicators.py --all --dry-run

  # Live run, all tickers
  python local/scripts/backfill_indicators.py --all

  # Single ticker
  python local/scripts/backfill_indicators.py --ticker AAPL

  # Cap number of tickers processed
  python local/scripts/backfill_indicators.py --all --limit 5

  # Tune the per-constituent delay (default: 5s)
  python local/scripts/backfill_indicators.py --all --delay 8
"""

import sys
import time
import argparse
from pathlib import Path
from statistics import mean
from typing import Optional

# ── project root resolution ──────────────────────────────────────────────────
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

env_local = project_root / ".env.local"
env_default = project_root / ".env"
if env_local.exists():
    load_dotenv(env_local)
elif env_default.exists():
    load_dotenv(env_default)

from functions.utils.db.connect import get_db_client  # noqa: E402
from functions.utils.news.sec_readers import (  # noqa: E402
    execute_reading_workers,
    fetch_textual_inertia_for_year,
    fetch_qa_tension_for_period
)
from functions.utils.news.ingest import setup_clients_and_embeddings  # noqa: E402
from functions.agents import create_textual_inertia_agent, create_tension_extractor_agent  # noqa: E402
from functions.utils.db.db_handler import (  # noqa: E402
    save_indicator_snapshot,
    save_textual_inertia_snapshot,
    save_qa_tension_snapshot
)


# ── ETF constituent lookup ────────────────────────────────────────────────────

def get_constituent_tickers(db, ticker: str) -> Optional[list]:
    """
    If `ticker` is an ETF in core_entities, return its constituent ticker list.
    Returns None for single stocks (i.e. process the ticker itself).
    """
    entity = db["core_entities"].find_one({"ticker": ticker.upper()})
    if entity and entity.get("is_etf", False):
        constituents = entity.get("constituents", [])
        tickers = [c.get("ticker", "").upper() for c in constituents if c.get("ticker")]
        if tickers:
            return tickers
    return None


def _run_single_constituent_multi_year(
    symbol: str,
    agents: tuple,
    years: list,
    dry_run: bool,
    parent_etf: Optional[str] = None,
    delay: float = 3.0,
    db = None
) -> dict:
    """
    Runs multi-year historical extractions (2021-2026) for ONE ticker.
    Generates annual 10-K textual inertia entries and 4 quarterly Q&A tension entries per year.
    Includes configurable pacing delay between LLM calls to prevent 429 rate limits.
    """
    textual_inertia_agent, tension_extractor_agent = agents
    symbol_upper = symbol.upper()
    
    annual_ti_results = []
    quarterly_qat_results = []

    print(f"  [*] Extracting 5-year historical indicators for {symbol_upper} ({years[0]}-{years[-1]}) | delay={delay}s between calls...")

    # 1. Annual Textual Inertia (2021 - 2026)
    for yr in years:
        ti_res = fetch_textual_inertia_for_year(symbol_upper, yr, textual_inertia_agent, db=db)
        score = ti_res.get("textual_inertia")
        reason = ti_res.get("textual_inertia_reason", "")
        
        if score is not None:
            annual_ti_results.append(score)
            print(f"    [FY{yr} 10-K] TI={score} | {reason[:60]}")
            if dry_run:
                print(f"    [DRY-RUN] Would insert textual_inertia_snapshots for {symbol_upper} FY={yr} (parent_etf={parent_etf}).")
            else:
                save_textual_inertia_snapshot(
                    ticker=symbol_upper,
                    fiscal_year=yr,
                    score=score,
                    reason=reason,
                    source="backfill_script",
                    parent_etf=parent_etf
                )

        # Rate-limit pacing delay after 10-K call
        if delay > 0:
            time.sleep(delay)

        # 2. Quarterly Q&A Tension (Q1 - Q4 per year)
        for qtr in [1, 2, 3, 4]:
            qat_res = fetch_qa_tension_for_period(symbol_upper, yr, qtr, tension_extractor_agent, db=db)
            q_score = qat_res.get("tension")
            q_reason = qat_res.get("tension_reason", "")
            
            if q_score is not None:
                quarterly_qat_results.append(q_score)
                print(f"    [FY{yr} Q{qtr}] QAT={q_score} | {q_reason[:60]}")
                if dry_run:
                    print(f"    [DRY-RUN] Would insert qa_tension_snapshots for {symbol_upper} FY={yr} Q{qtr} (parent_etf={parent_etf}).")
                else:
                    save_qa_tension_snapshot(
                        ticker=symbol_upper,
                        fiscal_year=yr,
                        fiscal_quarter=qtr,
                        score=q_score,
                        reason=q_reason,
                        source="backfill_script",
                        parent_etf=parent_etf
                    )

            # Rate-limit pacing delay after each quarterly transcript call
            if delay > 0:
                time.sleep(delay)

    # Return latest year summary for backward compatibility
    latest_ti = annual_ti_results[-1] if annual_ti_results else None
    latest_qat = quarterly_qat_results[-1] if quarterly_qat_results else None

    scores_summary = {
        "textual_inertia": latest_ti,
        "textual_inertia_reason": f"Historical multi-year 10-K backfill ({len(annual_ti_results)} years extracted).",
        "tension": latest_qat,
        "qa_tension": latest_qat,
        "tension_reason": f"Historical multi-quarter backfill ({len(quarterly_qat_results)} quarters extracted).",
        "annual_ti": annual_ti_results,
        "quarterly_qat": quarterly_qat_results
    }

    # Ensure a per-constituent sentiment_reports document exists in MongoDB
    if db is not None:
        _backpatch_report(db, symbol_upper, scores_summary, dry_run, parent_etf=parent_etf)

    return scores_summary


def _average_constituent_results(all_results: dict) -> dict:
    """
    Average non-None TI and tension scores across all constituent results.
    Returns a single scores dict in the shape save_indicator_snapshot() expects.
    """
    ti_vals = [v["textual_inertia"] for v in all_results.values() if v.get("textual_inertia") is not None]
    tension_vals = [v["tension"] for v in all_results.values() if v.get("tension") is not None]

    ti_reasons = [
        f"{sym}: {v.get('textual_inertia_reason', '')}"
        for sym, v in all_results.items()
        if v.get("textual_inertia_reason") and v.get("textual_inertia") is not None
    ]
    tension_reasons = [
        f"{sym}: {v.get('tension_reason', '')}"
        for sym, v in all_results.items()
        if v.get("tension_reason") and v.get("tension") is not None
    ]

    return {
        "textual_inertia": round(mean(ti_vals), 4) if ti_vals else None,
        "textual_inertia_reason": " | ".join(ti_reasons)[:600] if ti_reasons else "No constituent filings available.",
        "qa_tension": round(mean(tension_vals), 4) if tension_vals else None,
        "qa_tension_reason": " | ".join(tension_reasons)[:600] if tension_reasons else "No constituent transcripts available.",
    }


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_distinct_tickers(db) -> list:
    """
    Return all distinct tickers across sentiment_reports AND core_entities
    (including all constituent stocks in core_entities) so sentiment reports
    are produced for all constituent stocks, not just ETFs.
    """
    tickers = set(db["sentiment_reports"].distinct("ticker"))
    for entity in db["core_entities"].find():
        t = entity.get("ticker")
        if t:
            tickers.add(t.upper())
        for c in entity.get("constituents", []):
            ct = c.get("ticker")
            if ct:
                tickers.add(ct.upper())
    return sorted(list(tickers))


def _backpatch_report(db, ticker: str, scores: dict, dry_run: bool, parent_etf: str = None) -> str:
    """
    Back-patch or create a sentiment_reports document for this ticker/constituent.
    Returns the _id of the patched/created doc.
    """
    col = db["sentiment_reports"]
    ticker_clean = ticker.upper()
    doc = col.find_one({"ticker": ticker_clean}, sort=[("saved_at", -1)])
    
    update_data = {
        "ticker": ticker_clean,
        "parent_etf": parent_etf.upper() if parent_etf else (doc.get("parent_etf") if doc else None),
        "textual_inertia": scores.get("textual_inertia"),
        "textual_inertia_reason": scores.get("textual_inertia_reason", ""),
        "qa_tension": scores.get("qa_tension"),
        "qa_tension_reason": scores.get("qa_tension_reason", ""),
    }

    if dry_run:
        print(f"  [DRY-RUN] Would upsert sentiment_reports doc for {ticker_clean}: {update_data}")
        return "dry_run"

    if doc:
        col.update_one({"_id": doc["_id"]}, {"$set": update_data})
        print(f"  [OK] Updated sentiment_reports doc {doc['_id']} for {ticker_clean}.")
        return str(doc["_id"])
    else:
        print(f"  [!] No sentiment_reports doc found for {ticker_clean} — skipping back-patch.")
        return None


def _run_ticker(ticker: str, agents: tuple, db, dry_run: bool, delay: float, years: list = None) -> dict:
    """
    Run reading agents across target multi-year range (2021-2026).
    For ETFs: processes each constituent sequentially across all fiscal years and quarters.
    For single stocks: processes directly across all fiscal years and quarters.
    """
    ticker = ticker.upper()
    years = years or list(range(2021, 2027))
    print(f"\n[backfill] Processing {ticker} for years {years[0]} to {years[-1]}...")

    constituent_tickers = get_constituent_tickers(db, ticker)
    is_etf = constituent_tickers is not None

    if is_etf:
        print(f"  [ETF] {ticker} → {len(constituent_tickers)} constituents | delay={delay}s between each")
        all_results = {}
        for i, sym in enumerate(constituent_tickers):
            print(f"  [{i+1}/{len(constituent_tickers)}] {sym}")
            sym_data = _run_single_constituent_multi_year(sym, agents, years, dry_run, parent_etf=ticker, delay=delay, db=db)
            all_results[sym] = sym_data
            ti = sym_data.get("textual_inertia")
            qat = sym_data.get("tension")
            print(f"    Summary for {sym}: Latest TI={ti} | Latest QAT={qat}")

            if i < len(constituent_tickers) - 1:
                print(f"    [rate-limit] sleeping {delay}s...")
                time.sleep(delay)

        scores = _average_constituent_results(all_results)
        covered_ti = sum(1 for v in all_results.values() if v.get("textual_inertia") is not None)
        covered_qt = sum(1 for v in all_results.values() if v.get("tension") is not None)
        print(
            f"  [ETF ROLLUP] TI={scores['textual_inertia']} ({covered_ti}/{len(constituent_tickers)} constituents) "
            f"| QAT={scores['qa_tension']} ({covered_qt}/{len(constituent_tickers)} constituents)"
        )

        if dry_run:
            print(f"  [DRY-RUN] Would insert ETF rollup indicator_snapshots for {ticker}.")
        else:
            snap_id = save_indicator_snapshot(
                ticker=ticker,
                scores=scores,
                source="backfill_script",
                parent_etf=None
            )
            print(f"  [OK] ETF rollup indicator snapshots inserted for {ticker} (id={snap_id}).")

    else:
        print(f"  [STOCK] Running multi-year backfill directly on {ticker}")
        sym_data = _run_single_constituent_multi_year(ticker, agents, years, dry_run, parent_etf=None, delay=delay, db=db)
        scores = {
            "textual_inertia": sym_data.get("textual_inertia"),
            "textual_inertia_reason": sym_data.get("textual_inertia_reason", ""),
            "qa_tension": sym_data.get("tension"),
            "qa_tension_reason": sym_data.get("tension_reason", ""),
        }
        print(f"  TI  = {scores['textual_inertia']} | {scores['textual_inertia_reason'][:80]}")
        print(f"  QAT = {scores['qa_tension']} | {scores['qa_tension_reason'][:80]}")

    _backpatch_report(db, ticker, scores, dry_run)
    return {"ticker": ticker, "status": "ok", "scores": scores}


from functions.tools.edgar_tools import get_sec_10k_section  # noqa: E402
from functions.tools.transcript_tools import fetch_and_split_transcript  # noqa: E402


def pre_download_documents(target_tickers: list, years: list, db) -> None:
    """
    Phase 1: Pre-download and cache all SEC 10-Ks and earnings call transcripts
    into Cloudflare R2 and MongoDB BEFORE initializing or running any LLM agents.
    """
    print("\n" + "="*80)
    print(f"[PRE-DOWNLOAD PHASE] Pre-fetching documents for {len(target_tickers)} target tickers across {years[0]}-{years[-1]}...")
    print("="*80)

    # Collect all underlying symbols (including ETF constituents)
    all_symbols = set()
    for t in target_tickers:
        constituents = get_constituent_tickers(db, t)
        if constituents:
            all_symbols.update([c.upper() for c in constituents])
        else:
            all_symbols.add(t.upper())

    sorted_symbols = sorted(list(all_symbols))
    print(f"[PRE-DOWNLOAD] Resolved {len(sorted_symbols)} unique symbols to pre-download: {', '.join(sorted_symbols)}")

    for i, sym in enumerate(sorted_symbols):
        print(f"\n[PRE-DOWNLOAD {i+1}/{len(sorted_symbols)}] Pre-fetching filings & transcripts for {sym}...")
        
        # 1. SEC 10-K Filings (Item 1A) for current year and prior year comparison
        for yr in years:
            try:
                get_sec_10k_section(sym, yr, "1A")
                get_sec_10k_section(sym, yr - 1, "1A")
            except Exception as e:
                print(f"  [!] Notice: SEC 10-K for {sym} ({yr}) pre-fetch note: {e}")

        # 2. Earnings Call Transcripts (Q1 - Q4)
        for yr in years:
            for qtr in [1, 2, 3, 4]:
                try:
                    fetch_and_split_transcript(sym, year=yr, quarter=qtr)
                except Exception as e:
                    print(f"  [!] Notice: Transcript for {sym} Q{qtr} {yr} pre-fetch note: {e}")

    print("\n[PRE-DOWNLOAD PHASE] Completed pre-downloading and caching all documents into R2 / MongoDB.")
    print("="*80 + "\n")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Backfill textual inertia and Q&A tension scores into indicator_snapshots."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--all",
        action="store_true",
        help="Run for every distinct ticker in sentiment_reports.",
    )
    group.add_argument(
        "--ticker",
        type=str,
        help="Run for a single ticker symbol (e.g. AAPL).",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=2021,
        help="First fiscal year to backfill (default: 2021).",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=2026,
        help="Last fiscal year to backfill (default: 2026).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the number of tickers processed (useful with --all for testing).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=5.0,
        help="Seconds to wait between each constituent LLM call for ETFs (default: 5).",
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Pre-download and cache all documents into R2/MongoDB without running LLMs.",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip pre-downloading Phase 1 and run LLM evaluation directly.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print results without writing anything to MongoDB.",
    )
    parser.add_argument(
        "--env",
        type=str,
        default=None,
        help="Path to .env file (default: auto-detected .env.local).",
    )
    args = parser.parse_args()

    env_path = args.env or str(env_local if env_local.exists() else env_default)
    years_list = list(range(args.start_year, args.end_year + 1))

    print(f"[backfill_indicators] Target multi-year range: {args.start_year} to {args.end_year} ({len(years_list)} years)...")
    print("[backfill_indicators] Connecting to MongoDB...")
    client, db = get_db_client()
    print(f"[backfill_indicators] Connected to DB: {db.name}")

    # Determine ticker list
    if args.ticker:
        tickers = [args.ticker.upper()]
    else:
        tickers = [t.upper() for t in _get_distinct_tickers(db)]
        print(f"[backfill_indicators] Found {len(tickers)} tickers in sentiment_reports.")

    if args.limit:
        tickers = tickers[: args.limit]
        print(f"[backfill_indicators] Capped to {len(tickers)} tickers (--limit {args.limit}).")

    if not tickers:
        print("[backfill_indicators] No tickers to process. Exiting.")
        return

    # PHASE 1: Pre-download documents into Cloudflare R2 / MongoDB cache
    if not args.skip_download:
        pre_download_documents(tickers, years_list, db)

    if args.download_only:
        print("[backfill_indicators] --download-only specified. Pre-downloading completed. Exiting.")
        return

    if args.dry_run:
        print("[backfill_indicators] DRY-RUN mode — no writes will be made.\n")

    print(f"[backfill_indicators] Rate-limit delay between LLM calls: {args.delay}s\n")

    # PHASE 2: Build LLM agents and evaluate cached documents
    print("[backfill_indicators] Initialising LLM agents...")
    _, _, _, kimi_llm_config, _, _, _ = setup_clients_and_embeddings(
        env_path=env_path, csv_path=None
    )
    agents = (
        create_textual_inertia_agent("textual_inertia_prompt.txt", kimi_llm_config),
        create_tension_extractor_agent("tension_extractor_prompt.txt", kimi_llm_config),
    )
    print("[backfill_indicators] Agents ready.\n")

    # Process each top-level ticker sequentially across all years and quarters
    summary = []
    for i, ticker in enumerate(tickers):
        try:
            result = _run_ticker(ticker, agents, db, dry_run=args.dry_run, delay=args.delay, years=years_list)
            summary.append(result)
        except Exception as e:
            import traceback
            print(f"  [ERROR] Failed for {ticker}: {e}\n{traceback.format_exc()}")
            summary.append({"ticker": ticker, "status": "error", "error": str(e)})

        # Delay between top-level tickers too (not just constituents)
        if i < len(tickers) - 1:
            print(f"\n[rate-limit] Sleeping {args.delay}s before next ticker...")
            time.sleep(args.delay)

    # Print summary
    ok = [r for r in summary if r["status"] == "ok"]
    err = [r for r in summary if r["status"] == "error"]
    print(f"\n[backfill_indicators] Done. {len(ok)} succeeded / {len(err)} failed.")
    if err:
        print("Failures:")
        for r in err:
            print(f"  - {r['ticker']}: {r['error']}")


if __name__ == "__main__":
    main()
