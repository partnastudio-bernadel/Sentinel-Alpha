import os
import sys
import json
from typing import  Dict, Any

from langchain_core.messages import trim_messages
from langchain_core.runnables import RunnableConfig

script_dir = os.path.dirname(os.path.abspath(__file__))
sentiment_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))

if sentiment_dir not in sys.path:
    sys.path.insert(0, sentiment_dir)

from functions.utils.math.formulas import calculate_raw_sentiment, calculate_portfolio_sentiment, normalize_weights
from functions.tools.prepare_articles import assign_label
from functions.utils.logging.pipeline_logger import get_pipeline_logger
from functions.types.sentiment_state import SentimentState
from functions.utils.db.connect import get_db_client

# Node: Senior Sentiment Analyst (CIO) - aggregates and calculates final weighted sentiment
def cio_analyst_node(state: SentimentState, config: RunnableConfig) -> Dict[str, Any]:
    logger = get_pipeline_logger()
    logger.info("[cio_analyst_node] Executing consolidated CIO analyst node...")
    
    client, db = get_db_client()
    scored_collection = db["scored_articles"]
    
    # Fetch all scored articles by their IDs from MongoDB
    all_scored_ids = state.get("scored_article_ids", [])
    scored_articles = list(scored_collection.find({"_id": {"$in": all_scored_ids}}))
    
    # Execute reading workers qualitatively
    from functions.utils.news.sec_readers import execute_reading_workers
    from functions.agents import create_textual_inertia_agent, create_tension_extractor_agent, create_scribe_agent
    from functions.utils.news.ingest import setup_clients_and_embeddings
    
    config = config or {}
    env_path = config.get("configurable", {}).get("env_path", None)
    csv_path = config.get("configurable", {}).get("csv_path", None)
    _, llm_config, base_llm_config, kimi_llm_config, _, _, _ = setup_clients_and_embeddings(env_path=env_path, csv_path=csv_path)
    alt_api_key = os.getenv("NVIDIA_API_KEY_ALT")
    
    for attempt in range(3):
        try:
    

            textual_inertia_agent = create_textual_inertia_agent("textual_inertia_prompt.txt", kimi_llm_config)
            tension_extractor_agent = create_tension_extractor_agent("tension_extractor_prompt.txt", kimi_llm_config)
            scribe_agent = create_scribe_agent("scribe_prompt.txt", base_llm_config)
    
            tickers_to_query = [c["ticker"] for c in state.get("constituents", [])] if state.get("is_etf", False) else [state["ticker"]]
            indicators_report_data = execute_reading_workers(
                tickers_to_query=tickers_to_query,
                textual_inertia_agent=textual_inertia_agent,
                tension_extractor_agent=tension_extractor_agent
            )
    
            # Format the indicators context
            indicators_report_str = "--- QUALITATIVE INDICATORS (TEXTUAL INERTIA & TENSION) ---\n"
            for t_symbol, data in indicators_report_data.items():
                ti_val = data['textual_inertia'] if data['textual_inertia'] is not None else "N/A"
                te_val = data['tension'] if data['tension'] is not None else "N/A"
                indicators_report_str += (
                    f"Asset: {t_symbol}\n"
                    f"  - Textual Inertia Score: {ti_val} ({data['textual_inertia_reason']})\n"
                    f"  - Analyst Q&A Tension Score: {te_val} ({data['tension_reason']})\n\n"
                )
        
            decomp_report = f"ETF Decomposition Report:\n{json.dumps(state.get('decomp_data', {}), indent=2)}" if state.get("is_etf", False) else "ETF Decomposition Report: Single Stock."
    
            # Re-structure scored articles to match expected schema input for CIO
            cio_articles_input = []
            for doc in scored_articles:
                cio_articles_input.append({
                    "title": doc.get("title", ""),
                    "source": doc.get("source", ""),
                    "published_at": doc.get("date", ""),
                    "sentiment_label": doc.get("sentiment_label", "Neutral"),
                    "sentiment_score": doc.get("sentiment_score", 0.0),
                    "confidence": doc.get("confidence", 0.0),
                    "risk_factors": doc.get("risk_factors", []),
                    "reasoning_summary": doc.get("reasoning_summary", ""),
                    "flagged": doc.get("flagged", False),
                    "flag_reason": doc.get("flag_reason", None)
                })
        
            combined_message = (
                f"You are requested to analyze the sentiment for ticker: {state['ticker']}\n\n"
                f"Here is the data retrieved by the pipeline:\n\n"
                f"--- ETF DECOMPOSITION DATA ---\n"
                f"{decomp_report}\n\n"
                f"--- SCORED NEWS ARTICLES DATA ---\n"
                f"{json.dumps(cio_articles_input, indent=2)}\n\n"
                f"{indicators_report_str}\n"
                "IMPORTANT: If qualitative indicators are N/A (e.g. for an IPO), do not assume neutral risk. "
                "Treat the lack of historical filings as an 'Unknown Risk Premium' and do not let it dilute strong news sentiment.\n\n"
                "Now, use your registered tools (normalize_weights, calculate_raw_sentiment, "
                "calculate_portfolio_sentiment, assign_label) to perform the mathematical calculations "
                "and generate the final JSON report according to your rules."
            )
    
            # Register tools
            from langchain_core.tools import tool
            from functions.tools.mongo_toolkits import get_mongodb_toolkit
            from langchain_nvidia_ai_endpoints import ChatNVIDIA
            llm_for_mongo = ChatNVIDIA(model=base_llm_config["model"], api_key=base_llm_config.get("api_key", os.getenv("NVIDIA_API_KEY")))
            mongo_toolkit = get_mongodb_toolkit(llm=llm_for_mongo)
    
            @tool
            def query_mongodb_mql(query: str) -> str:
                """Executes a MongoDB MQL query against historical sentiment databases and returns the results.
                IMPORTANT: The query MUST be a string of the form: `db.collectionName.aggregate([...])`.
                Only aggregation queries are supported.
                """
                mql_tool = next((t for t in mongo_toolkit.get_tools() if "query" in t.name.lower()), None)
                if mql_tool:
                    try:
                        return mql_tool.invoke({"query": query})
                    except Exception as e:
                        return f"Error executing query: {e}"
                return "Tool not available."
        
            from pydantic import BaseModel, Field

            class CalculateSentimentInput(BaseModel):
                title: str = Field(..., description="The exact title/headline of the article to calculate raw sentiment.")

            @tool(args_schema=CalculateSentimentInput)
            def calculate_raw_sentiment_tool(title: str) -> float:
                """Calculate the raw sentiment score for a given article by its title."""
                for art in cio_articles_input:
                    if art.get("title") == title:
                        return calculate_raw_sentiment(art)
                return 0.0
        
            @tool
            def calculate_portfolio_sentiment_tool(assets: list) -> float:
                """Calculate weighted portfolio sentiment."""
                return calculate_portfolio_sentiment(assets)
        
            @tool
            def normalize_weights_tool(weights: dict) -> dict:
                """Normalize portfolio weights."""
                return normalize_weights(weights)
        
            @tool
            def assign_label_tool(score: float) -> str:
                """Assign sentiment label based on score."""
                return assign_label(score)
        
            cio_tools = [calculate_raw_sentiment_tool, calculate_portfolio_sentiment_tool, normalize_weights_tool, assign_label_tool, query_mongodb_mql]
    
            from langgraph.prebuilt import create_react_agent
            from functions.utils.common.config import build_chat_model
            from functions.utils.db.prompt_manager import get_prompt
            from functions.types.sentiment import SentimentReport
    
            cio_llm = build_chat_model(
                model=base_llm_config.get("model"),
                base_url=base_llm_config.get("base_url"),
                api_key=base_llm_config.get("api_key")
            )
    
            cio_output_schema_str = json.dumps(SentimentReport.model_json_schema(), indent=2)
            cio_prompt_template = get_prompt("cio_prompt.txt")
            
            cio_system_prompt = cio_prompt_template.format(SCHEMA="Input data is provided in JSON format below.", EXAMPLES="See inline", OUTPUT=cio_output_schema_str)
            cio_system_prompt = cio_system_prompt.replace("{", "{{").replace("}", "}}")
    
            cio_agent = create_react_agent(cio_llm, tools=cio_tools, prompt=cio_system_prompt)
    
            # GOAL 2: Stateful Message Trimming (apply trimmer)
            from langchain_core.messages import trim_messages, HumanMessage
    
            trimmed_messages = trim_messages(
                [HumanMessage(content=combined_message)],
                max_tokens=4000,
                strategy="last",
                token_counter=cio_llm,
                include_system=True
            )
    
            response = cio_agent.invoke({"messages": trimmed_messages})
            final_report_msg = response["messages"][-1].content
    
            # Goal 4: Enforce Pydantic schema generation with robust JSON parsing
            from functions.types.sentiment import SentimentReport
            from functions.tools.custom_reply import extract_json_array

            final_report = {}
            if final_report_msg and isinstance(final_report_msg, str) and final_report_msg.strip():
                try:
                    # First try standard json loads
                    final_report = json.loads(final_report_msg)
                except Exception:
                    # Fallback to extract_json_array or regex JSON block parsing
                    parsed = extract_json_array(final_report_msg)
                    if isinstance(parsed, dict):
                        final_report = parsed
                    elif isinstance(parsed, list) and len(parsed) > 0:
                        final_report = parsed[0]
                    else:
                        final_report = {"error": "JSON parse error", "raw": final_report_msg}
            else:
                final_report = {"error": "Empty response from CIO LLM", "raw": str(final_report_msg)}

        
            # Compliance override checks
            from functions.utils.news.compliance import validate_compliance_limits
            final_report = validate_compliance_limits(
                ticker=state["ticker"],
                is_etf=state.get("is_etf", False),
                constituents=state.get("constituents", []),
                final_report=final_report,
                merged_result=cio_articles_input,
                indicators_report_data=indicators_report_data,
                scribe_agent=scribe_agent
            )
    
            return {"results": final_report}
        except Exception as e:
            error_str = str(e).lower()
            
            # Log the detailed exception and traceback exclusively to logs/pipeline.log
            import traceback
            import logging
            from functions.utils.logging.pipeline_logger import log_to_file_only
            detailed_err = f"NIM API error on model {base_llm_config.get('model')}: {e}\n{traceback.format_exc()}"
            log_to_file_only(logger, logging.ERROR, detailed_err)
            
            is_api_error = (
                "503" in error_str or 
                "502" in error_str or 
                "504" in error_str or 
                "resourceexhausted" in error_str or 
                "429" in error_str or 
                "400" in error_str or 
                "depleted" in error_str or 
                "model_not_supported" in error_str or
                "expecting value" in error_str
            )
            if is_api_error and attempt < 2:
                primary_tooling_model = os.getenv("NVIDIA_TOOLING_MODEL", "deepseek-ai/deepseek-v4-flash").strip('"\' ')
                fallback_model_70b = os.getenv("NVIDIA_TOOLING_MODEL_ALT", "meta/llama-3.1-70b-instruct").strip('"\' ')
                fallback_model_8b = os.getenv("NVIDIA_BASE_MODEL", "meta/llama-3.1-8b-instruct").strip('"\' ')
                
                current_model = base_llm_config.get("model")
                if current_model == primary_tooling_model:
                    logger.warning(f"[cio_analyst_node] API error on primary tooling model. Falling back to: {fallback_model_70b}")
                    base_llm_config["model"] = fallback_model_70b
                    continue
                elif current_model == fallback_model_70b:
                    logger.warning(f"[cio_analyst_node] API error on secondary tooling model. Falling back to: {fallback_model_8b}")
                    base_llm_config["model"] = fallback_model_8b
                    continue
                elif "429" in error_str and alt_api_key:
                    logger.warning("[cio_analyst_node] 429 Rate Limit hit. Switching to alternate API key and retrying...")
                    base_llm_config["api_key"] = alt_api_key
                    kimi_llm_config["api_key"] = alt_api_key
                    continue
                else:
                    logger.warning(f"[cio_analyst_node] API error on tooling model {current_model}. Retrying attempt {attempt + 2}/3...")
                    continue
            raise e
