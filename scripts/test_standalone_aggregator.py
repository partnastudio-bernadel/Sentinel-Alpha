import os
import sys
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

env_path = project_root / ".env.local"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

from functions.utils.db.connect import get_db_client
from functions.utils.db.db_handler import save_sentiment_report, aggregate_leaderboard_for_ticker

def test_aggregation():
    print("=== Testing Standalone Leaderboard Aggregator & Sentiment Report Persistence ===")
    client, db = get_db_client()
    
    # 1. Test saving a dummy report
    test_report = {
        "ticker": "XLK",
        "metadata": {"timestamp": "2026-07-18T13:00:00Z", "article_count": 5},
        "aggregate_score": -0.25,
        "aggregate_label": "Negative",
        "velocity": -0.10,
        "reasoning": "Test sentiment report for XLK showing tech weakness.",
        "warnings": ["15% drift check passed"],
        "articles": []
    }
    
    report_id = save_sentiment_report("XLK", test_report)
    print(f"[+] Saved test report for XLK. Report ID: {report_id}")
    
    # 2. Test running standalone aggregation for core tickers
    test_tickers = ["XLK", "QQQ", "SPY", "XLF", "XLE", "AAPL", "MSFT"]
    print("\n[+] Running standalone aggregation for tickers...")
    for ticker in test_tickers:
        res = aggregate_leaderboard_for_ticker(ticker)
        print(f"  - Ticker: {res.get('ticker'):<6} | Current Sentiment: {res.get('current_sentiment'):<7.4f} | Velocity: {res.get('velocity'):<7.4f} | Status: {res.get('status')}")
        
    print("\n[+] Querying updated sentiment_leaderboard collection...")
    leaderboard_docs = list(db["sentiment_leaderboard"].find({}, {"_id": 0}))
    for doc in leaderboard_docs:
        print(f"  Leaderboard Doc: Ticker={doc.get('ticker'):<6} | Current={doc.get('current_sentiment'):<7.4f} | Velocity={doc.get('velocity'):<7.4f} | Last Updated={doc.get('last_updated')}")

    print("\n[+] Querying sentiment_reports collection count...")
    report_count = db["sentiment_reports"].count_documents({})
    print(f"  Total sentiment_reports in DB: {report_count}")
    print("=== Test Complete ===")

if __name__ == "__main__":
    test_aggregation()
