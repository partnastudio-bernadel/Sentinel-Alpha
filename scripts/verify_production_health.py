import os
import sys
import subprocess
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

# Set project paths (assuming script is located in sentiment/scripts/)
script_dir = os.path.dirname(os.path.abspath(__file__))
sentiment_dir = os.path.dirname(script_dir) # This resolves to sentiment/
if sentiment_dir not in sys.path:
    sys.path.insert(0, sentiment_dir)

from functions.utils.db.connect import get_db_client

def check_process_running(process_name):
    try:
        output = subprocess.check_output(["pgrep", "-fa", "python"], text=True)
        for line in output.strip().split("\n"):
            if process_name in line:
                return True, line
        return False, None
    except Exception:
        return False, None

def check_log_file(path):
    if not os.path.exists(path):
        return False, "File does not exist."
    size = os.path.getsize(path)
    if size == 0:
        return True, "File exists but is empty (no logs written yet)."
    
    # Read last 5 lines
    try:
        with open(path, "r") as f:
            lines = f.readlines()
            last_lines = "".join(lines[-5:])
            return True, f"Size: {size} bytes\nLast lines:\n{last_lines}"
    except Exception as e:
        return True, f"File exists but error reading: {e}"

def parse_iso_datetime(dt_str):
    if not dt_str:
        return None
    if dt_str.endswith("Z"):
        dt_str = dt_str[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(dt_str)
    except Exception:
        return None

def main():
    print("================ SENTINEL PRODUCTION DIAGNOSTIC CHECK ================")
    
    # Load env
    env_path = os.path.join(sentiment_dir, ".env.local")
    load_dotenv(env_path)
    
    # 1. Check Background Daemons
    print("\n[1] Checking System Processes...")
    scheduler_running, scheduler_cmd = check_process_running("macro_scheduler_cli.py")
    if scheduler_running:
        print(f"✅ Macro Scheduler Daemon is RUNNING (PID/Cmd: {scheduler_cmd})")
    else:
        print("❌ Macro Scheduler Daemon is NOT running (check tmux session!)")

    orchestrator_running, orchestrator_cmd = check_process_running("sentinel_orchestrator.py")
    if orchestrator_running:
        print(f"✅ Sentinel Orchestrator Daemon is RUNNING (PID/Cmd: {orchestrator_cmd})")
    else:
        print("❌ Sentinel Orchestrator Daemon is NOT running (check tmux session!)")

    # 2. Check Log files
    print("\n[2] Checking Log Files...")
    pipeline_log = os.path.join(sentiment_dir, "logs", "pipeline.log")
    orchestrator_log = os.path.join(sentiment_dir, "logs", "sentinel_orchestrator.log")
    
    print(f"Checking {pipeline_log}:")
    exists, log_info = check_log_file(pipeline_log)
    if exists:
        print(f"✅ Active\n{log_info}")
    else:
        print(f"⚠️ Inactive ({log_info})")
        
    print(f"\nChecking {orchestrator_log}:")
    exists, log_info = check_log_file(orchestrator_log)
    if exists:
        print(f"✅ Active\n{log_info}")
    else:
        print(f"ℹ️ Idle/Pending ({log_info}) - Will populate after the hourly cron runs.")

    # 3. Check MongoDB Collection Health
    print("\n[3] Checking MongoDB Collection Counts...")
    try:
        client, db = get_db_client()
        print("✅ Connected to MongoDB Atlas cluster.")
        
        collections = [
            ("macro_calendar", "Seeded Economic Events"),
            ("fred_mappings", "FRED Series Mappings"),
            ("macro_baselines", "Standard Deviation Baselines"),
            ("scored_articles", "Scored News Sentiment Cache"),
            ("sentiment_reports", "Persisted Sentiment Reports"),
            ("sentiment_leaderboard", "ETF Sentiment Leaderboard"),
            ("core_entities", "Seeded ETFs/Constituents"),
            ("prompts", "Seeded LLM Prompts")
        ]
        
        for col_name, desc in collections:
            col = db[col_name]
            count = col.count_documents({})
            print(f"  - {col_name:<20} | Count: {count:<6} | ({desc})")
            
        # Specific health stats
        completed_macro = db["macro_calendar"].count_documents({"status": "completed"})
        pending_macro = db["macro_calendar"].count_documents({"status": "pending"})
        print(f"\nMacro Calendar Stats: Completed={completed_macro}, Pending={pending_macro}")
        
        # 4. Check Hourly Job Run Status (Last 60 Minutes)
        print("\n[4] Checking Hourly Job Status (Last 60 Minutes)...")
        now_utc = datetime.now(timezone.utc)
        one_hour_ago = now_utc - timedelta(hours=1)
        
        core_entities_col = db["core_entities"]
        leaderboard_col = db["sentiment_leaderboard"]
        
        core_entities = list(core_entities_col.find({}))
        tickers = [doc.get("ticker") for doc in core_entities if doc.get("ticker")]
        
        if not tickers:
            print("⚠️ No core ETF entities found in database to verify.")
        else:
            print(f"Verifying sentiment update runs for {len(tickers)} core tickers:")
            ran_count = 0
            for ticker in sorted(tickers):
                leaderboard_entry = leaderboard_col.find_one({"ticker": ticker})
                if leaderboard_entry:
                    last_updated_str = leaderboard_entry.get("last_updated")
                    last_updated_dt = parse_iso_datetime(last_updated_str)
                    
                    if last_updated_dt:
                        time_diff = now_utc - last_updated_dt
                        minutes_ago = int(time_diff.total_seconds() / 60)
                        
                        if last_updated_dt >= one_hour_ago:
                            print(f"  - {ticker:<6} | ✅ Ran {minutes_ago} mins ago ({last_updated_str})")
                            ran_count += 1
                        else:
                            hours_ago = time_diff.total_seconds() / 3600
                            print(f"  - {ticker:<6} | ❌ Out of sync - Ran {hours_ago:.1f} hours ago ({last_updated_str})")
                    else:
                        print(f"  - {ticker:<6} | ❌ Out of sync - Invalid last_updated timestamp: {last_updated_str}")
                else:
                    print(f"  - {ticker:<6} | ❌ Out of sync - No leaderboard entry found in MongoDB.")
                    
            print(f"\nSentiment Job Completion Rate in last 60 minutes: {ran_count}/{len(tickers)} ({ran_count/len(tickers)*100:.1f}%)")
            if ran_count < len(tickers):
                print("🚨 WARNING: Some core sentiment jobs did not run in the last hour.")
            else:
                print("🎉 SUCCESS: All core sentiment jobs successfully executed in the last hour!")
                
    except Exception as e:
        print(f"❌ MongoDB Connection failed during health checks: {e}")

    print("\n======================================================================")

if __name__ == "__main__":
    main()
