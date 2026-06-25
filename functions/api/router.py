import os
import json
import logging
from typing import Dict, Any, Literal
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import PydanticOutputParser

logger = logging.getLogger(__name__)

class IntentClassification(BaseModel):
    intent: Literal["INTENT_UPDATE_MACRO", "INTENT_SCORE_SECTOR", "INTENT_CONVERSATIONAL", "INTENT_UNKNOWN"] = Field(
        description="The classified intent of the user request or webhook payload."
    )
    extracted_parameters: Dict[str, Any] = Field(
        description="Any parameters extracted from the payload, such as ticker symbols, event names, etc.",
        default_factory=dict
    )
    reasoning: str = Field(description="Brief reasoning for this classification.")

class IntentRouter:
    """
    Parses incoming webhook payloads and natural language queries,
    classifies the intent, and routes to the appropriate Sentinel execution graph or RAG fallback.
    """
    def __init__(self, llm=None):
        if llm:
            self.llm = llm
        elif os.environ.get("NVIDIA_API_KEY"):
            from langchain_nvidia_ai_endpoints import ChatNVIDIA
            model = os.environ.get("NVIDIA_BASE_MODEL", "meta/llama-3.1-8b-instruct")
            base_url = os.environ.get("NVIDIA_API_ENDPOINT", "https://integrate.api.nvidia.com/v1")
            self.llm = ChatNVIDIA(model=model, temperature=0, base_url=base_url)
        else:
            self.llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        self.parser = PydanticOutputParser(pydantic_object=IntentClassification)
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", "You are the Intent Router for Sentinel Alpha, an autonomous financial intelligence engine.\n\n"
                       "Your job is to classify incoming user requests or webhook payloads into one of the following intents:\n"
                       "1. INTENT_UPDATE_MACRO: The user or system wants to fetch, ingest, or update macro-economic events (e.g. CPI, GDP, calendar sweeps).\n"
                       "2. INTENT_SCORE_SECTOR: The user or system wants to score sentiment for a specific ticker, ETF, or run a portfolio scan.\n"
                       "3. INTENT_CONVERSATIONAL: The user is asking a general question about the market, asking why Sentinel made a decision, or asking for current state/context.\n"
                       "4. INTENT_UNKNOWN: The intent cannot be determined.\n\n"
                       "Extract any relevant parameters (e.g., 'ticker': 'AAPL', 'event': 'CPI m/m').\n\n"
                       "{format_instructions}"),
            ("user", "Incoming Request/Payload: {payload}")
        ])
        
        self.chain = self.prompt | self.llm | self.parser

    def classify_intent(self, payload: str | Dict[str, Any]) -> IntentClassification:
        """Classify the intent of the incoming payload."""
        if isinstance(payload, dict):
            payload_str = json.dumps(payload)
        else:
            payload_str = str(payload)
            
        try:
            result = self.chain.invoke({
                "payload": payload_str,
                "format_instructions": self.parser.get_format_instructions()
            })
            return result
        except Exception as e:
            logger.error(f"Failed to classify intent: {e}")
            return IntentClassification(
                intent="INTENT_UNKNOWN", 
                extracted_parameters={}, 
                reasoning=f"Error parsing intent: {str(e)}"
            )

    def conversational_rag_fallback(self, query: str, db_client) -> str:
        """
        RAG fallback for INTENT_CONVERSATIONAL.
        Queries the MongoDB governance collections to provide intelligent context.
        """
        # We will retrieve recent items from governance_reasoning_chains or audit logs
        # For this skeleton, we construct a prompt with db context
        
        # NOTE: db_client should be the PyMongo client initialized via get_db_client()
        try:
            db = db_client["sentinel"]
            recent_chains = list(db["governance_reasoning_chains"].find().sort("timestamp", -1).limit(3))
            
            context = "Recent Sentinel Decisions:\n"
            for chain in recent_chains:
                context += f"- ID: {chain.get('_id')}, Agent: {chain.get('agent_id')}, Status: {chain.get('status')}\n"
        except Exception as e:
            context = "Could not retrieve recent database context."
            logger.error(f"RAG DB query failed: {e}")

        rag_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are Sentinel, a financial intelligence AI. "
                       "Answer the user's conversational query using the following recent database context if relevant:\n\n{context}"),
            ("user", "{query}")
        ])
        
        rag_chain = rag_prompt | self.llm
        response = rag_chain.invoke({"context": context, "query": query})
        return response.content

    def route_and_execute(self, payload: str | Dict[str, Any], db_client=None) -> Dict[str, Any]:
        """
        Full pipeline: Classify intent and trigger appropriate action.
        """
        classification = self.classify_intent(payload)
        logger.info(f"Routed intent: {classification.intent}")
        
        if classification.intent == "INTENT_CONVERSATIONAL":
            query = payload if isinstance(payload, str) else json.dumps(payload)
            response = self.conversational_rag_fallback(query, db_client)
            return {
                "status": "success",
                "intent": classification.intent,
                "response": response,
                "parameters": classification.extracted_parameters
            }
            
        elif classification.intent == "INTENT_UPDATE_MACRO":
            # Here we would normally invoke the LangGraph tool / script natively.
            # E.g., importing macro_scheduler_cli and running it.
            return {
                "status": "triggered_macro_pipeline",
                "intent": classification.intent,
                "parameters": classification.extracted_parameters
            }
            
        elif classification.intent == "INTENT_SCORE_SECTOR":
            # Here we would invoke the Sentiment Graph tool.
            return {
                "status": "triggered_sentiment_pipeline",
                "intent": classification.intent,
                "parameters": classification.extracted_parameters
            }
            
        else:
            return {
                "status": "error",
                "intent": classification.intent,
                "message": "Could not determine intent."
            }
