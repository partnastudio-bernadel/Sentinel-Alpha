import os
import sys
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import logging

from functions.governance.runtime import IntentCoreRuntime
from functions.api.router import IntentRouter
from functions.utils.db.connect import get_db_client
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# ===== API Models =====

class ReviewDecision(BaseModel):
    reviewer_id: str
    decision: str  # approved, rejected, modified
    rationale: Optional[str] = None
    modification: Optional[Dict[str, Any]] = None

class WebhookPayload(BaseModel):
    payload: Dict[str, Any]

class ChatPayload(BaseModel):
    query: str

class ExecuteMacroPayload(BaseModel):
    event: str
    indicator: str

class ExecuteSentimentPayload(BaseModel):
    ticker: str
    limit: Optional[int] = 10
    holdings: Optional[int] = None

# ===== FastAPI App =====

app = FastAPI(
    title="IntentCore Reflex & Governance API",
    description="Reflex Router and Governance backend for Sentinel",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize DB and Runtime
project_root = Path(__file__).resolve().parents[2]
scripts_dir = project_root / "scripts"

# Load environment variables
env_path = project_root / ".env.local"
if not env_path.exists():
    env_path = project_root / ".env"
load_dotenv(env_path)

# Note: We are migrating away from SQLite. 
# For now runtime is initialized to prevent breaking old UI code,
# but new review queue goes to MongoDB.
db_client, mongo_db = get_db_client()

# Initialize Intent Router
router = IntentRouter()

# ===== Helper to run scripts natively =====

def run_script_in_background(script_name: str, args: List[str]):
    script_path = scripts_dir / script_name
    cmd = [sys.executable, str(script_path)] + args
    try:
        logger.info(f"Executing: {' '.join(cmd)}")
        subprocess.Popen(cmd)
    except Exception as e:
        logger.error(f"Failed to execute {script_name}: {e}")

# ===== REFLEX ROUTER (WEBHOOKS) =====

@app.post("/webhooks/news")
@app.post("/webhooks/forexfactory")
async def handle_webhook(payload: Request, background_tasks: BackgroundTasks):
    """Reflex Webhook Endpoint."""
    data = await payload.json()
    result = router.route_and_execute(data, db_client=db_client)
    
    # We could trigger background tasks here based on result.intent
    if result.get("intent") == "INTENT_UPDATE_MACRO":
        background_tasks.add_task(run_script_in_background, "macro_scheduler_cli.py", ["--sweep"])
    elif result.get("intent") == "INTENT_SCORE_SECTOR":
        ticker = result.get("parameters", {}).get("ticker", "SPY")
        background_tasks.add_task(run_script_in_background, "news_sentiment_cli.py", ["--ticker", ticker])
        
    return result

@app.post("/webhooks/chat")
async def handle_chat(payload: ChatPayload):
    """Reflex NLP Chat Endpoint."""
    result = router.route_and_execute(payload.query, db_client=db_client)
    return result

# ===== NATIVE EXECUTION ENDPOINTS =====

@app.post("/execute/macro")
def execute_macro(payload: ExecuteMacroPayload, background_tasks: BackgroundTasks):
    """Directly trigger macro ingestion."""
    args = ["--event", payload.event, "--indicator", payload.indicator]
    background_tasks.add_task(run_script_in_background, "macro_ingestion_cli.py", args)
    return {"status": "triggered", "script": "macro_ingestion_cli.py", "args": args}

@app.post("/execute/sentiment")
def execute_sentiment(payload: ExecuteSentimentPayload, background_tasks: BackgroundTasks):
    """Directly trigger sentiment ingestion."""
    args = ["--ticker", payload.ticker]
    if payload.holdings is not None:
        args.extend(["--holdings", str(payload.holdings)])
    else:
        args.extend(["--limit", str(payload.limit)])
        
    background_tasks.add_task(run_script_in_background, "news_sentiment_cli.py", args)
    return {"status": "triggered", "script": "news_sentiment_cli.py", "args": args}

@app.post("/execute/scheduler")
def execute_scheduler(sweep: bool = False, fetch: bool = False, background_tasks: BackgroundTasks = None):
    """Directly trigger the scheduler script."""
    args = []
    if sweep:
        args.append("--sweep")
    if fetch:
        args.append("--fetch")
    background_tasks.add_task(run_script_in_background, "macro_scheduler_cli.py", args)
    return {"status": "triggered", "script": "macro_scheduler_cli.py", "args": args}

@app.post("/execute/baselines")
def execute_baselines(limit: str = "all", update: str = None, background_tasks: BackgroundTasks = None):
    """Directly trigger the macro baselines sync."""
    args = []
    if update:
        args.extend(["--update", update])
    else:
        args.extend(["--limit", str(limit)])
    background_tasks.add_task(run_script_in_background, "macro_baselines_cli.py", args)
    return {"status": "triggered", "script": "macro_baselines_cli.py", "args": args}

# ===== GOVERNANCE ENDPOINTS (MongoDB) =====

@app.get("/api/reviews/pending")
def get_pending_reviews():
    """Get pending reviews from MongoDB governance queue."""
    collection = mongo_db["governance_review_queue"]
    pending = list(collection.find({"status": "pending"}))
    for p in pending:
        p["_id"] = str(p["_id"])
    return pending

@app.post("/api/reviews/{chain_id}/decision")
def submit_review_decision(chain_id: str, decision: ReviewDecision, background_tasks: BackgroundTasks):
    """
    Submit operator decision for a compliance flag.
    Triggers re-calculation if modified.
    """
    collection = mongo_db["governance_review_queue"]
    result = collection.update_one(
        {"chain_id": chain_id},
        {"$set": {
            "status": "completed", 
            "decision": decision.decision,
            "reviewer_id": decision.reviewer_id,
            "modification": decision.modification
        }}
    )
    
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Review not found in queue.")
        
    # Remediation Loop: Trigger recalculation with overrides
    if decision.decision in ["approved", "modified"] and decision.modification:
        mod_type = decision.modification.get("type", "sentiment")
        overrides_json = json.dumps(decision.modification.get("overrides", {}))
        
        if mod_type == "sentiment":
            ticker = decision.modification.get("ticker", "SPY")
            args = ["--ticker", ticker, "--override-betas", overrides_json]
            background_tasks.add_task(run_script_in_background, "news_sentiment_cli.py", args)
            logger.info(f"Triggered recalculation for {ticker} with overrides.")
        elif mod_type == "macro":
            event = decision.modification.get("event", "CPI")
            args = ["--event", event, "--override-weights", overrides_json]
            background_tasks.add_task(run_script_in_background, "macro_ingestion_cli.py", args)
            logger.info(f"Triggered recalculation for {event} with overrides.")
            
    return {"success": True, "chain_id": chain_id, "decision": decision.decision}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
