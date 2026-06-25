import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import AIMessage
from functions.api.router import IntentRouter

@patch('functions.api.router.ChatOpenAI')
def test_intent_router_classification(MockChatOpenAI):
    router = IntentRouter()
    
    # Mock LLM response for MACRO
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = AIMessage(content='{"intent": "INTENT_UPDATE_MACRO", "extracted_parameters": {"event": "CPI"}, "reasoning": "Macro test"}')
    router.llm = mock_llm
    
    payload = {"title": "CPI jumps 0.4%"}
    result = router.route_and_execute(payload, db_client=None)
    
    assert result["intent"] == "INTENT_UPDATE_MACRO"
    assert result["parameters"]["event"] == "CPI"
    
@patch('functions.api.router.ChatOpenAI')
def test_intent_router_sentiment(MockChatOpenAI):
    router = IntentRouter()
    
    # Mock LLM response for SENTIMENT
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = AIMessage(content='{"intent": "INTENT_SCORE_SECTOR", "extracted_parameters": {"ticker": "AAPL"}, "reasoning": "Sentiment test"}')
    router.llm = mock_llm
    
    payload = "Apple announces new iPhone"
    result = router.route_and_execute(payload, db_client=None)
    
    assert result["intent"] == "INTENT_SCORE_SECTOR"
    assert result["parameters"]["ticker"] == "AAPL"
