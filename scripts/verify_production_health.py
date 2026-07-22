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

def check_system_memory():
    print("\n[2] Checking System Memory & Swap Usage...")
    try:
        import psutil
        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        total_gb = vm.total / (1024 ** 3)
        used_gb = vm.used / (1024 ** 3)
        avail_gb = vm.available / (1024 ** 3)
        print(f"  RAM Usage:  {used_gb:.2f} GB / {total_gb:.2f} GB ({vm.percent}%) | Available: {avail_gb:.2f} GB")
        
        if vm.percent > 85.0:
            print("  🚨 WARNING: High system memory usage detected (>85%)!")
        else:
            print("  ✅ RAM usage within normal parameters.")

        swap_total_mb = swap.total / (1024 ** 2)
        swap_used_mb = swap.used / (1024 ** 2)
        if swap.total > 0:
            print(f"  Swap Space: {swap_used_mb:.1f} MB / {swap_total_mb:.1f} MB ({swap.percent}%)")
            print("  ✅ Swap space is ACTIVE.")
        else:
            print("  ⚠️ WARNING: No Swap Space configured on system (0 MB). Risk of OOM killer on memory spikes!")

        print("\n  Top Python Processes Memory Footprint:")
        python_procs = []
        for p in psutil.process_iter(['pid', 'name', 'cmdline', 'memory_info', 'memory_percent']):
            try:
                cmdline = " ".join(p.info['cmdline'] or [])
                if "python" in p.info['name'].lower() or "python" in cmdline.lower():
                    rss_mb = p.info['memory_info'].rss / (1024 ** 2) if p.info['memory_info'] else 0
                    mem_pct = p.info['memory_percent'] or 0.0
                    python_procs.append((p.info['pid'], rss_mb, mem_pct, cmdline))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        python_procs.sort(key=lambda x: x[1], reverse=True)
        if python_procs:
            for pid, rss_mb, mem_pct, cmd in python_procs[:5]:
                short_cmd = cmd if len(cmd) <= 70 else cmd[:67] + "..."
                print(f"    - PID {pid:<6} | RSS: {rss_mb:6.1f} MB ({mem_pct:4.1f}%) | {short_cmd}")
        else:
            print("    - No active Python processes detected.")

    except ImportError:
        try:
            free_out = subprocess.check_output(["free", "-h"], text=True)
            print("  System Memory (via free -h):\n" + free_out.strip())
        except Exception as e:
            print(f"  ⚠️ Could not query memory info: {e}")

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

    # 2. Check System Memory & Swap
    check_system_memory()

    # 3. Check Log files
    print("\n[3] Checking Log Files...")
    sentiment_log = os.path.join(sentiment_dir, "logs", "sentiment_pipeline.log")
    macro_log = os.path.join(sentiment_dir, "logs", "macro_pipeline.log")
    orchestrator_log = os.path.join(sentiment_dir, "logs", "sentinel_orchestrator.log")
    legacy_log = os.path.join(sentiment_dir, "logs", "pipeline.log")
    
    for log_path, label in [
        (sentiment_log, "Sentiment Pipeline Log"),
        (macro_log, "Macro Pipeline Log"),
        (orchestrator_log, "Sentinel Orchestrator Log"),
        (legacy_log, "Legacy Pipeline Log")
    ]:
        if os.path.exists(log_path) or label != "Legacy Pipeline Log":
            print(f"Checking {label} ({log_path}):")
            exists, log_info = check_log_file(log_path)
            if exists:
                print(f"✅ Active\n{log_info}\n")
            else:
                print(f"⚠️ Inactive ({log_info})\n")

    # 4. Check MongoDB Collection Health
    print("\n[4] Checking MongoDB Collection Counts...")
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
        
        # 5. Check Hourly Job Run Status (Last 60 Minutes)
        print("\n[5] Checking Hourly Job Status (Last 60 Minutes)...")
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
                    scores_obj = leaderboard_entry.get("scores", {})
                    direct_s = scores_obj.get("direct", leaderboard_entry.get("current_sentiment", 0.0))
                    rolled_s = scores_obj.get("rolled_up", leaderboard_entry.get("current_sentiment", 0.0))
                    scores_str = f"Direct: {direct_s:.2f} | RolledUp: {rolled_s:.2f}"
                    
                    if last_updated_dt:
                        time_diff = now_utc - last_updated_dt
                        minutes_ago = int(time_diff.total_seconds() / 60)
                        
                        if last_updated_dt >= one_hour_ago:
                            print(f"  - {ticker:<6} | ✅ Ran {minutes_ago} mins ago | {scores_str} ({last_updated_str})")
                            ran_count += 1
                        else:
                            hours_ago = time_diff.total_seconds() / 3600
                            print(f"  - {ticker:<6} | ❌ Out of sync - Ran {hours_ago:.1f} hours ago | {scores_str} ({last_updated_str})")
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
