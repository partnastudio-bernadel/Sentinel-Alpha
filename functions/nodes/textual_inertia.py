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
from functions.agents import create_textual_inertia_agent

# 3. Node: Textual Inertia (10-K Deviation analysis)
def textual_inertia_node(state: MacroState, config: RunnableConfig, store: BaseStore) -> Dict[str, Any]:
    logger = get_pipeline_logger()
    logger.info("[textual_inertia_node] Executing textual inertia node (10-K SEC filings analyzer)...")
    
    # Resolve agent configurations
    config = config or {}
    env_path = config.get("configurable", {}).get("env_path", None)
    csv_path = config.get("configurable", {}).get("csv_path", None)
    _, _, _, kimi_llm_config, _, _, _ = setup_clients_and_embeddings(env_path=env_path, csv_path=csv_path)
    
    # Instantiate the agent natively using the factory
    textual_inertia_agent = create_textual_inertia_agent(
        prompt_id="textual_inertia_prompt.txt",
        llm_config=kimi_llm_config
    )
    
    # Memory Pointers: Load heavy 10-K text content from MongoDBStore to keep graph state lightweight
    filings_pointers = state.get("filings_pointers", {})
    filings_content = {}
    for ticker, pointer in filings_pointers.items():
        stored_item = store.get(namespace=("sec_filings", ticker), key=pointer)
        if stored_item:
            filings_content[ticker] = stored_item.value
            
    results = {}
    for ticker, doc in filings_content.items():
        messages = [
            SystemMessage(content="You analyze 10-K filings for textual inertia."),
            HumanMessage(content=f"Analyze corporate filings (10-K) for ticker {ticker}:\n\n{doc[:4000]}...")
        ]
        
        trimmed = trim_messages(
            messages,
            max_tokens=2000,
            strategy="last",
            token_counter=ChatNVIDIA(model="meta/llama-3.1-8b-instruct", api_key=os.getenv("NVIDIA_API_KEY", ""))
        )
        
        response = textual_inertia_agent.invoke({"input": trimmed[-1].content})
        results[ticker] = response.content
        
    return {"textual_inertia_results": results}
