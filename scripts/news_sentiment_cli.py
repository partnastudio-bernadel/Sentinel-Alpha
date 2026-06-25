import sys
import os
import json
import argparse
import uuid
from dotenv import load_dotenv

# Resolve script paths and ensure the sentiment directory is in Python's lookup path
script_dir = os.path.dirname(os.path.abspath(__file__))
sentiment_dir = os.path.dirname(script_dir)

if sentiment_dir not in sys.path:
    sys.path.insert(0, sentiment_dir)

try:
    from functions.graphs.sentiment_graph import build_sentiment_graph
except ImportError as e:
    print(f"Error importing required sentiment graph: {e}", file=sys.stderr)
    print("Ensure you have activated your virtual environment and installed the dependencies.", file=sys.stderr)
    sys.exit(1)

def run_sentiment_analysis(
    ticker: str,
    limit: int = 5,
    holdings: str = "5",
    csv_path: str = None,
    env_path: str = None
) -> dict:
    """Runs the LangGraph news sentiment analysis pipeline natively."""
    if env_path is None:
        env_path = os.path.join(sentiment_dir, ".env.local")
        if not os.path.exists(env_path):
            env_path = os.path.join(sentiment_dir, ".env")
            
    if csv_path is None:
        csv_path = os.path.join(sentiment_dir, "data", "financial_sentiment.csv")
        
    load_dotenv(env_path)

    # Configure graph runner
    app = build_sentiment_graph()
    thread_id = str(uuid.uuid4())
    config = {
        "configurable": {
            "thread_id": thread_id,
            "env_path": env_path,
            "csv_path": csv_path
        }
    }
    
    initial_state = {
        "ticker": ticker.upper().strip(),
        "timeframe_days": 3,  # default fallback
        "limit": limit,
        "holdings": holdings
    }
    
    final_state = None
    for output in app.stream(initial_state, config, stream_mode="values"):
        final_state = output

    if final_state and "results" in final_state:
        return final_state["results"]
    
    if final_state and "error" in final_state and final_state["error"]:
        raise RuntimeError(final_state["error"])
        
    return {"error": "Failed to retrieve results from pipeline execution."}

def main():
    parser = argparse.ArgumentParser(
        description="CLI utility for running the LangGraph News Sentiment Analyzer."
    )
    parser.add_argument(
        "--ticker", "-t",
        type=str,
        default="AAPL",
        help="Stock ticker symbol to analyze (default: AAPL)."
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=5,
        help="Max number of news articles to retrieve and score (default: 5)."
    )
    parser.add_argument(
        "--csv", "-c",
        type=str,
        default=None,
        help="Path to calibration CSV file (default: data/financial_sentiment.csv)."
    )
    parser.add_argument(
        "--holdings", "-k",
        type=str,
        default="5",
        help="Number of top ETF holdings to analyze or 'all' (default: 5)."
    )
    parser.add_argument(
        "--env", "-e",
        type=str,
        default=None,
        help="Path to environment file (default: .env.local)."
    )
    
    args = parser.parse_args()
    
    print(f"Starting news sentiment analysis for {args.ticker} (Limit: {args.limit}, Holdings: {args.holdings})...")
    
    try:
        report = run_sentiment_analysis(
            ticker=args.ticker,
            limit=args.limit,
            holdings=args.holdings,
            csv_path=args.csv,
            env_path=args.env
        )
        print("\n================ SENTIMENT ANALYSIS REPORT ================")
        print(json.dumps(report, indent=2))
    except Exception as e:
        print(f"\n[Error] Failed to complete analysis: {e}", file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    main()
