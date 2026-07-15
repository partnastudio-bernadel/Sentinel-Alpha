import os
import sys
from typing import Dict, Any
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore
from langchain_core.messages import SystemMessage, HumanMessage, trim_messages
from langchain_nvidia_ai_endpoints import ChatNVIDIA

script_dir = os.path.dirname(os.path.abspath(__file__))
sentiment_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))

if sentiment_dir not in sys.path:
    sys.path.insert(0, sentiment_dir)

from functions.types.macro_state import MacroState
from functions.utils.logging.pipeline_logger import get_pipeline_logger
from functions.utils.news.ingest import setup_clients_and_embeddings
from functions.agents import create_tension_extractor_agent

# 4. Node: Tension Extractor (Earnings Call Transcript analyzer)
def tension_extractor_node(state: MacroState, config: RunnableConfig, store: BaseStore) -> Dict[str, Any]:
    logger = get_pipeline_logger()
    logger.info("[tension_extractor_node] Executing tension extractor node (Earnings Call Q&A analyzer)...")
    
    config = config or {}
    env_path = config.get("configurable", {}).get("env_path", None)
    csv_path = config.get("configurable", {}).get("csv_path", None)
    _, _, _, kimi_llm_config, _, _, _ = setup_clients_and_embeddings(env_path=env_path, csv_path=csv_path)
    
    tension_extractor_agent = create_tension_extractor_agent(
        prompt_id="tension_extractor_prompt.txt",
        llm_config=kimi_llm_config
    )
    
    # Memory Pointers: Load heavy transcripts content from MongoDBStore to keep state lightweight
    transcripts_pointers = state.get("transcripts_pointers", {})
    transcripts_content = {}
    for ticker, pointer in transcripts_pointers.items():
        stored_item = store.get(namespace=("transcripts", ticker), key=pointer)
        if stored_item:
            transcripts_content[ticker] = stored_item.value
            
    results = {}
    for ticker, doc in transcripts_content.items():
        messages = [
            SystemMessage(content="You analyze transcripts for corporate tension."),
            HumanMessage(content=f"Analyze corporate earnings call transcripts for ticker {ticker}:\n\n{doc[:4000]}...")
        ]
        
        trimmed = trim_messages(
            messages,
            max_tokens=2000,
            strategy="last",
            token_counter=ChatNVIDIA(model="meta/llama-3.1-8b-instruct", api_key=os.getenv("NVIDIA_API_KEY", ""))
        )
        
        response = tension_extractor_agent.invoke({"input": trimmed[-1].content})
        results[ticker] = response.content
        
    return {"tension_extractor_results": results}
