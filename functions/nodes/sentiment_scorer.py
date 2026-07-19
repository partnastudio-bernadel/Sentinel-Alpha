import os
import sys
from typing import  Dict, Any

from langchain_core.runnables import RunnableConfig

script_dir = os.path.dirname(os.path.abspath(__file__))
sentiment_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))

if sentiment_dir not in sys.path:
    sys.path.insert(0, sentiment_dir)


from functions.utils.logging.pipeline_logger import get_pipeline_logger
from functions.types.sentiment_state import SentimentState
from functions.utils.db.connect import get_db_client
from functions.nodes.ingest_news import get_article_id

# Node: Sentiment Scorer (calls LLM to score articles, then stores results to MongoDB collection 'scored_articles')
def sentiment_scorer_node(state: SentimentState, config: RunnableConfig) -> Dict[str, Any]:
    logger = get_pipeline_logger()
    articles_to_score = state.get("articles_payload", [])
    
    if not articles_to_score:
        logger.info("[sentiment_scorer_node] No articles to score.")
        return {}
        
    logger.info(f"[sentiment_scorer_node] Scoring {len(articles_to_score)} articles...")
    
    # Import setup function
    from functions.utils.news.ingest import setup_clients_and_embeddings
    config = config or {}
    env_path = config.get("configurable", {}).get("env_path", None)
    csv_path = config.get("configurable", {}).get("csv_path", None)
    _, llm_config, base_llm_config, _, _, _, embeddings = setup_clients_and_embeddings(env_path=env_path, csv_path=csv_path)
    
    # Setup LangGraph agents
    from functions.agents import create_scorer_agent
    
    # Goal 3: Inject MongoDB vector search retriever tool
    from functions.tools.mongo_toolkits import get_mongodb_retriever_tool
    from langchain_core.tools import tool
    
    retriever_tool = get_mongodb_retriever_tool(embeddings)
    
    @tool
    def retrieve_calibration_examples(query: str) -> str:
        """Search for similar financial sentence calibration examples and their corresponding sentiment classifications."""
        return retriever_tool.invoke(query)
        
    # Wrap with react agent to execute tools
    from langgraph.prebuilt import create_react_agent
    from functions.utils.common.config import build_chat_model
    llm = build_chat_model(
        model=llm_config.get("model"),
        base_url=llm_config.get("base_url"),
        api_key=llm_config.get("api_key")
    )
    
    from functions.utils.db.prompt_manager import get_prompt
    from functions.types.sentiment import SentimentAnalysisReport
    import json
    
    prompt_template = get_prompt("sentiment_scorer.txt")
    schema_str = json.dumps(SentimentAnalysisReport.model_json_schema(), indent=2)
    system_prompt = prompt_template.format(SCHEMA=schema_str, EXAMPLES="Use the matching 'calibration_examples' list provided inline inside the user message for each article.")
    system_prompt = system_prompt.replace("{", "{{").replace("}", "}}")
    
    from functions.types.sentiment import SentimentAnalysisReport
    scorer_agent = create_react_agent(llm, tools=[], prompt=system_prompt)
    
    # Score in batches
    from functions.utils.news.scoring import batch_score_articles, async_batch_score_articles
    
    is_async = state.get("async_mode", False)
    
    try:
        if is_async:
            merged_results, _ = async_batch_score_articles(
                all_articles=articles_to_score,
                scorer_agent=scorer_agent
            )
        else:
            merged_results, _ = batch_score_articles(
                all_articles=articles_to_score,
                scorer_agent=scorer_agent
            )
    except Exception as e:
        error_str = str(e).lower()
        
        # Log the detailed exception and traceback exclusively to logs/pipeline.log
        import traceback
        import logging
        from functions.utils.logging.pipeline_logger import log_to_file_only
        detailed_err = f"NIM API error during sentiment scoring: {e}\n{traceback.format_exc()}"
        log_to_file_only(logger, logging.ERROR, detailed_err)
        
        is_api_error = (
            "402" in error_str or 
            "500" in error_str or
            "502" in error_str or 
            "503" in error_str or 
            "504" in error_str or 
            "429" in error_str or 
            "depleted" in error_str or 
            "400" in error_str or 
            "model_not_supported" in error_str or
            "expecting value" in error_str or
            "tool" in error_str or
            "prompt template" in error_str or
            "internal server error" in error_str
        )
        if is_api_error:
            logger.warning("[sentiment_scorer_node] API Error or Model Not Supported hit on primary model. Falling back to NVIDIA Base Model...")
            # Rebuild LLM using NVIDIA base model
            fallback_model = os.getenv("NVIDIA_BASE_MODEL_ALT", "moonshotai/kimi-k2.6").strip('"\' ')
            llm = build_chat_model(
                model=fallback_model,
                base_url=base_llm_config.get("base_url"),
                api_key=base_llm_config.get("api_key")
            )
            scorer_agent = create_react_agent(llm, tools=[], prompt=system_prompt)
            
            if is_async:
                merged_results, _ = async_batch_score_articles(
                    all_articles=articles_to_score,
                    scorer_agent=scorer_agent
                )
            else:
                merged_results, _ = batch_score_articles(
                    all_articles=articles_to_score,
                    scorer_agent=scorer_agent
                )
        else:
            raise e
    
    # Save scored results back to MongoDB collection 'scored_articles'
    client, db = get_db_client()
    scored_collection = db["scored_articles"]
    
    new_scored_ids = []
    
    scored_articles_output = []
    if isinstance(merged_results, dict):
        scored_articles_output = merged_results.get("articles", [])
    elif isinstance(merged_results, list):
        for item in merged_results:
            if isinstance(item, dict):
                scored_articles_output.extend(item.get("articles", []))
            else:
                scored_articles_output.append(item)
    else:
        scored_articles_output = merged_results
        
    # Match scored results to raw articles to build final schema
    for scored in scored_articles_output:
        # Match using title/url or index
        title = scored.get("title", "")
        # Find raw article
        matched_raw = None
        for raw in articles_to_score:
            if raw.get("title", "") == title:
                matched_raw = raw
                break
                
        if matched_raw:
            art_id = get_article_id(matched_raw)
            document = {
                "_id": art_id,
                "date": matched_raw.get("published_at", ""),
                "title": title,
                "primary_ticker": matched_raw.get("primary_ticker", state["ticker"]),
                "tickers": matched_raw.get("tickers", [matched_raw.get("ticker", state["ticker"])]),
                "source": matched_raw.get("source", ""),
                "sentiment_label": scored.get("sentiment_label", "Neutral") if isinstance(scored, dict) else getattr(scored, "sentiment_label", "Neutral"),
                "sentiment_score": float(scored.get("sentiment_score", 0.0) if isinstance(scored, dict) else getattr(scored, "sentiment_score", 0.0)),
                "confidence": float(scored.get("confidence", 0.0) if isinstance(scored, dict) else getattr(scored, "confidence", 0.0)),
                "risk_factors": scored.get("risk_factors", []) if isinstance(scored, dict) else getattr(scored, "risk_factors", []),
                "reasoning_summary": scored.get("reasoning_summary", "") if isinstance(scored, dict) else getattr(scored, "reasoning_summary", ""),
                "flagged": scored.get("flagged", False) if isinstance(scored, dict) else getattr(scored, "flagged", False),
                "flag_reason": scored.get("flag_reason", None) if isinstance(scored, dict) else getattr(scored, "flag_reason", None)
            }
            # Save full document directly to MongoDB collection 'scored_articles'
            scored_collection.replace_one({"_id": art_id}, document, upsert=True)
            logger.info(
                f"[SCORER CACHE STORE] Saved scored sentiment for '{title}' to MongoDB. "
                f"Sentiment: {document['sentiment_label']} "
                f"(Score: {document['sentiment_score']:.2f})"
            )
            new_scored_ids.append(art_id)
            
    return {
        "scored_article_ids": state.get("scored_article_ids", []) + new_scored_ids
    }
