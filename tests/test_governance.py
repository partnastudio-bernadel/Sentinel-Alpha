import pytest
from langgraph.errors import NodeInterrupt
from functions.nodes.governance import governor_node, evaluate_compliance
from unittest.mock import patch, MagicMock

def test_evaluate_compliance_turnover():
    state = {
        "current_weights": {"SPY": 0.50},
        "proposed_weights": {"SPY": 0.70}  # 20% shift, > 15% limit
    }
    result = evaluate_compliance(state)
    assert not result["is_compliant"]
    assert any("15%" in v for v in result["violations"])

def test_evaluate_compliance_missing_indicator():
    state = {
        "macro_shock": None
    }
    result = evaluate_compliance(state)
    assert not result["is_compliant"]
    assert any("macro_shock" in v for v in result["violations"])

@patch('functions.nodes.governance.DatabaseManager')
def test_governor_node_reflex_interrupt(MockDBManager):
    state = {
        "is_autonomous": False, # Reflex mode
        "proposed_weights": {"AAPL": 0.50},
        "current_weights": {"AAPL": 0.20} # 30% shift
    }
    
    with pytest.raises(NodeInterrupt):
        governor_node(state)

@patch('functions.nodes.governance.DatabaseManager')
def test_governor_node_heartbeat_workaround(MockDBManager):
    state = {
        "is_autonomous": True, # Heartbeat mode
        "proposed_weights": {"AAPL": 0.50},
        "current_weights": {"AAPL": 0.20} # 30% shift
    }
    
    # Should not raise exception, should apply workaround
    new_state = governor_node(state)
    assert new_state["proposed_weights"]["AAPL"] == 0.20 # Reverted to safe baseline
    assert new_state["governance_status"] == "workaround_applied"
