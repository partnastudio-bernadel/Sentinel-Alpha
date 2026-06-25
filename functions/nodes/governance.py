import logging
from typing import Dict, Any, List
from langgraph.errors import NodeInterrupt
from functions.utils.db.governance_manager import DatabaseManager
from functions.models.reasoning_chain import ReasoningChain

logger = logging.getLogger(__name__)

def evaluate_compliance(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluates the state for compliance violations.
    Checks for:
    1. Allocation drift > 15% (mocked or extracted from state)
    2. Missing critical indicators or empty payloads
    """
    violations = []
    
    # 1. Check for Missing Critical Indicators
    # Example: If Macro graph and missing standard deviation or actual value
    if "macro_shock" in state and state.get("macro_shock") is None:
        violations.append("Missing critical macro indicators (macro_shock is None).")
        
    # If Sentiment graph and no articles were fetched
    if "articles" in state and len(state.get("articles", [])) == 0:
        violations.append("Empty article payload. Cannot calculate reliable sentiment.")
        
    # 2. Check for Allocation Turnover Limit
    proposed_weights = state.get("proposed_weights", {})
    current_weights = state.get("current_weights", {})
    
    for asset, new_w in proposed_weights.items():
        old_w = current_weights.get(asset, 0)
        if abs(new_w - old_w) > 0.15:
            violations.append(f"Turnover limit breached: {asset} shifted by more than 15%.")
            
    # Check if there are flagged articles
    flagged_articles = state.get("flagged_articles", [])
    if flagged_articles:
        violations.append(f"Found {len(flagged_articles)} flagged articles requiring review.")
        
    return {
        "is_compliant": len(violations) == 0,
        "violations": violations
    }

def governor_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    The IntentCore Governor Node for LangGraph.
    Acts as the back-door validation gateway.
    """
    logger.info("Governor Node executing...")
    
    # Check if this is an autonomous background run (Heartbeat) or live webhook (Reflex)
    is_autonomous = state.get("is_autonomous", True)
    
    # Check if an operator override is already present in the state
    operator_decision = state.get("governance_decision")
    if operator_decision:
        logger.info(f"Applying operator override: {operator_decision}")
        # Apply the override to the state
        if "beta_overrides" in state:
            logger.info("Applied beta_overrides from operator.")
        # Proceed without raising interrupts since human already decided
        return state

    # Run compliance evaluation
    compliance = evaluate_compliance(state)
    
    if compliance["is_compliant"]:
        logger.info("State is fully compliant. Proceeding to production write.")
        return state
        
    # Violations found
    logger.warning(f"Compliance violations detected: {compliance['violations']}")
    
    # Initialize DB Manager
    db = DatabaseManager()
    
    # Create an audit ReasoningChain
    chain = ReasoningChain(
        agent_id="IntentGovernor",
        agent_role="Compliance Gateway",
        task="Validate State Output",
        situation="Detected compliance anomalies during state validation.",
        risks=compliance["violations"],
        requires_review=True,
        execution_status="halted" if not is_autonomous else "workaround_applied"
    )
    chain_id = db.save_reasoning_chain(chain)
    
    # Determine severity (Critical vs Non-Critical)
    # E.g., >15% turnover or missing macro is critical.
    # For now, let's treat any violation in Reflex as critical, and in Heartbeat as non-critical.
    is_critical = any("Turnover" in v or "Missing" in v for v in compliance["violations"])
    
    if is_autonomous:
        # HEARTBEAT MODE: Apply workarounds and log report, don't pause.
        logger.info("Heartbeat Mode: Applying workarounds and filing compliance report.")
        
        # Add to Review Queue
        db.add_to_review_queue(chain_id, priority="high")
        
        # Apply workarounds to the state so the pipeline can finish gracefully
        if "proposed_weights" in state:
            logger.info("Workaround: Reverting proposed weights to safe baselines.")
            # Dummy workaround logic: reset to current
            state["proposed_weights"] = state.get("current_weights", {})
            
        state["governance_status"] = "workaround_applied"
        return state
        
    else:
        # REFLEX MODE: Live webhook or chat
        if is_critical:
            logger.error("Reflex Mode: Critical violations. Raising NodeInterrupt to pause execution.")
            db.add_to_review_queue(chain_id, priority="urgent")
            # Update state with pending status before pausing
            state["governance_status"] = "pending_review"
            state["chain_id"] = chain_id
            raise NodeInterrupt(f"Critical Compliance Flags Raised: {compliance['violations']}")
        else:
            logger.info("Reflex Mode: Non-critical violations. Logging and proceeding.")
            db.add_to_review_queue(chain_id, priority="normal")
            state["governance_status"] = "flagged"
            return state
