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
    from functions.graphs.macro_graph import build_macro_graph
except ImportError as e:
    print(f"Error importing required macro graph: {e}", file=sys.stderr)
    print("Ensure you have activated your virtual environment and installed the dependencies.", file=sys.stderr)
    sys.exit(1)

def run_macro_ingestion_single(
    event_name: str,
    indicator_name: str,
    env_path: str = None
) -> dict:
    """Runs the LangGraph macro surprise ingestion pipeline natively."""
    if env_path is None:
        env_path = os.path.join(sentiment_dir, ".env.local")
        if not os.path.exists(env_path):
            env_path = os.path.join(sentiment_dir, ".env")
            
    load_dotenv(env_path)

    # Configure graph runner
    app = build_macro_graph()
    thread_id = str(uuid.uuid4())
    config = {
        "configurable": {
            "thread_id": thread_id,
            "env_path": env_path
        }
    }
    
    # Setup state
    initial_state = {
        "indicators": [indicator_name],
        "timeframe_days": 30,
        "force_refresh": False,
        "filings_pointers": {},
        "transcripts_pointers": {}
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
        description="CLI utility for running the LangGraph Macro Ingestion pipeline."
    )
    parser.add_argument(
        "--event", "-v",
        type=str,
        default="CPI m/m",
        help="Target economic calendar event name to harvest (default: 'CPI m/m')."
    )
    parser.add_argument(
        "--indicator", "-i",
        type=str,
        default="CPI",
        help="Baseline macro indicator to calculate rolling standard deviation for (default: 'CPI')."
    )
    parser.add_argument(
        "--env", "-e",
        type=str,
        default=None,
        help="Path to environment configuration file (default: .env.local)."
    )
    
    args = parser.parse_args()
    
    print(f"Starting macro surprise calculation for '{args.event}' using indicator '{args.indicator}'...")
    
    try:
        report = run_macro_ingestion_single(
            event_name=args.event,
            indicator_name=args.indicator,
            env_path=args.env
        )
        print("\n================ MACRO INGESTION SURPRISE REPORT ================")
        print(json.dumps(report, indent=2))
    except Exception as e:
        print(f"\n[Error] Failed to complete macro calculations: {e}", file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    main()
