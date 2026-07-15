from typing import TypedDict, List, Dict, Any, Optional


# Define the macro state graph state
class MacroState(TypedDict):
    indicators: List[str]
    timeframe_days: int
    force_refresh: bool
    
    # Store references/pointers to heavy SEC filings / Earnings Call transcript documents
    filings_pointers: Dict[str, str]
    transcripts_pointers: Dict[str, str]
    
    # Executed inputs and results payloads
    forex_events: List[Dict[str, Any]]
    av_indicators: Dict[str, Any]
    textual_inertia_results: Dict[str, Any]
    tension_extractor_results: Dict[str, Any]
    
    # Final consolidated thesis output
    results: Dict[str, Any]
    error: Optional[str]
