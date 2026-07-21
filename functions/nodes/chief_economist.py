import os
import sys
import json
from typing import Dict, Any
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_nvidia_ai_endpoints import ChatNVIDIA

script_dir = os.path.dirname(os.path.abspath(__file__))
sentiment_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))

if sentiment_dir not in sys.path:
    sys.path.insert(0, sentiment_dir)

from functions.types.macro_state import MacroState
from functions.utils.logging.pipeline_logger import get_pipeline_logger
from functions.utils.news.ingest import setup_clients_and_embeddings

# 5. Node: Chief Macro Economist (Consolidation & output generation)
def chief_economist_node(state: MacroState, config: RunnableConfig) -> Dict[str, Any]:
    logger = get_pipeline_logger("macro")
    logger.info("[chief_economist_node] Consolidating all macroeconomic nodes into final report...")
    
    config = config or {}
    env_path = config.get("configurable", {}).get("env_path", None)
    csv_path = config.get("configurable", {}).get("csv_path", None)
    _, _, base_llm_config, _, _, _, _ = setup_clients_and_embeddings(env_path=env_path, csv_path=csv_path)
    base_llm_config["model"] = "minimaxai/minimax-m3"
    alt_api_key = os.getenv("NVIDIA_API_KEY_ALT")
    
    # Consolidate state details
    macro_summary = {
        "forex_events": state.get("forex_events", []),
        "av_indicators": state.get("av_indicators", {}),
        "textual_inertia_results": state.get("textual_inertia_results", {}),
        "tension_extractor_results": state.get("tension_extractor_results", {})
    }
    
    from functions.utils.db.prompt_manager import get_prompt
    from functions.types.macro import MacroReport
    
    prompt_template = get_prompt("chief_macro_economist_prompt.txt")
    schema_content = json.dumps(MacroReport.model_json_schema(), indent=2)
    system_prompt = prompt_template.format(SCHEMA=schema_content, EXAMPLES="")
    
    from functions.utils.common.config import build_chat_model
    from functions.types.macro import MacroReport
    from langgraph.prebuilt import create_react_agent
    
    cio_message = (
        "Generate the final macroeconomic analysis report based on these indicators:\n\n"
        f"{json.dumps(macro_summary, indent=2)}\n\n"
        "Generate the final structured JSON compliance output."
    )
    inputs = {"messages": [("human", cio_message)]}

    max_retries = 3
    attempt = 0
    final_report_msg = ""
    
    # Goal 3: Inject MongoDBDatabaseToolkit Text-to-MQL tools
    from functions.tools.mongo_toolkits import get_mongodb_toolkit
    
    while attempt < max_retries:
        attempt += 1
        try:
            llm_for_mongo = ChatNVIDIA(
                model=base_llm_config["model"],
                api_key=base_llm_config.get("api_key", os.getenv("NVIDIA_API_KEY", ""))
            )
            mongo_toolkit = get_mongodb_toolkit(llm=llm_for_mongo)
            
            @tool
            def query_mongodb_mql(query: str) -> str:
                """Executes a MongoDB MQL query against historical macro databases and returns the results.
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

            llm = build_chat_model(
                model=base_llm_config["model"],
                base_url=base_llm_config.get("base_url"),
                api_key=base_llm_config.get("api_key")
            )
            
            agent_executor = create_react_agent(
                model=llm,
                tools=[query_mongodb_mql],
                prompt=system_prompt
            )
            
            result = agent_executor.invoke(inputs)
            final_report_msg = result["messages"][-1].content
            break
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
            if is_api_error and attempt < max_retries:
                primary_tooling_model = "minimaxai/minimax-m3"
                fallback_model_70b = os.getenv("NVIDIA_TOOLING_MODEL_ALT", "meta/llama-3.1-70b-instruct").strip('"\' ')
                fallback_model_8b = os.getenv("NVIDIA_BASE_MODEL", "meta/llama-3.1-8b-instruct").strip('"\' ')
                
                current_model = base_llm_config.get("model")
                if current_model == primary_tooling_model:
                    logger.warning(f"[chief_economist_node] API error on primary tooling model. Falling back to: {fallback_model_70b}")
                    base_llm_config["model"] = fallback_model_70b
                    continue
                elif current_model == fallback_model_70b:
                    logger.warning(f"[chief_economist_node] API error on secondary tooling model. Falling back to: {fallback_model_8b}")
                    base_llm_config["model"] = fallback_model_8b
                    continue
                elif "429" in error_str and alt_api_key:
                    logger.warning("[chief_economist_node] 429 Rate Limit hit. Switching to alternate API key and retrying...")
                    base_llm_config["api_key"] = alt_api_key
                    continue
                else:
                    logger.warning(f"[chief_economist_node] API error on tooling model {current_model}. Retrying attempt {attempt + 1}/{max_retries}...")
                    continue
            raise e
    
    # Goal 4: Enforce Pydantic schema generation with LangChain's with_structured_output
    from functions.types.macro import MacroReport
    from langchain_core.prompts import ChatPromptTemplate

    parse_attempts = 0
    max_parse_retries = 3
    parse_llm_config = dict(base_llm_config)
    final_report = None

    while parse_attempts < max_parse_retries:
        parse_attempts += 1
        try:
            parse_llm = build_chat_model(
                model=parse_llm_config.get("model"),
                base_url=parse_llm_config.get("base_url"),
                api_key=parse_llm_config.get("api_key")
            )
            structured_llm = parse_llm.with_structured_output(MacroReport)
            prompt = ChatPromptTemplate.from_messages([
                ("system", "You are an expert JSON structured parser. Extract the exact values into the strict MacroReport schema."),
                ("human", "{raw_report}")
            ])
            chain = prompt | structured_llm
            final_report_pydantic = chain.invoke({"raw_report": final_report_msg})
            final_report = final_report_pydantic.model_dump()
            break
        except Exception as parse_err:
            parse_err_str = str(parse_err).lower()
            logger.warning(f"[chief_economist_node] Pydantic parsing attempt {parse_attempts}/{max_parse_retries} failed: {parse_err}")
            
            if ("429" in parse_err_str or "rate limit" in parse_err_str or "too many requests" in parse_err_str) and parse_attempts < max_parse_retries:
                if alt_api_key and parse_llm_config.get("api_key") != alt_api_key:
                    logger.info("[chief_economist_node] 429 on Pydantic parsing. Switching to alternate API key...")
                    parse_llm_config["api_key"] = alt_api_key
                else:
                    backoff_seconds = parse_attempts * 5
                    logger.info(f"[chief_economist_node] Rate limit hit during Pydantic parsing. Sleeping for {backoff_seconds}s before retrying...")
                    time.sleep(backoff_seconds)
                continue
            elif parse_attempts < max_parse_retries:
                time.sleep(2)
                continue
            else:
                logger.error(f"Error parsing Macro CIO response with Pydantic after retries: {parse_err}")
                try:
                    # Strip markdown braces if raw fallback needed
                    clean_msg = final_report_msg
                    if "```json" in clean_msg:
                        clean_msg = clean_msg.split("```json")[1].split("```")[0].strip()
                    elif "```" in clean_msg:
                        clean_msg = clean_msg.split("```")[1].split("```")[0].strip()
                    start_idx = clean_msg.find('{')
                    end_idx = clean_msg.rfind('}')
                    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                        clean_msg = clean_msg[start_idx:end_idx+1].strip()
                    final_report = json.loads(clean_msg)
                except Exception:
                    final_report = {"error": "JSON parse error", "raw": final_report_msg}
                break
        
    return {"results": final_report}
