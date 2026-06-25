import os
import json
from datetime import datetime, timezone

# Resolve paths relative to this file
current_file_dir = os.path.dirname(os.path.abspath(__file__))
logs_dir = os.path.abspath(os.path.join(current_file_dir, "..", "..", "..", "logs"))
_COMPLIANCE_LOG_PATH = os.path.join(logs_dir, "compliance_audit.jsonl")

def log_compliance_event(event_type: str, metadata: dict, log_path: str = _COMPLIANCE_LOG_PATH) -> None:
    """Writes a compliance audit event to the local JSONL log file.
    
    Args:
        event_type (str): Type of compliance event (e.g. 'OVERRIDE', 'COMPLIANCE_CHECK').
        metadata (dict): Event payload details.
        log_path (str): Target log file path.
    """
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    
    entry = {
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        **metadata
    }
    
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
        
    print(f"[ComplianceLogger] Event of type '{event_type}' written to: {os.path.abspath(log_path)}")
