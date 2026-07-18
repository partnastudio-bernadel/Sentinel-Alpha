from dataclasses import dataclass
from typing import TypedDict, List, Dict, Any, Optional
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from .utils.common.config import build_chat_model
from .utils.db.prompt_manager import get_prompt
from .utils.common.sanitize import read_file_content

class AgentSpec(TypedDict):
    name: str
    description: str
    prompt_id: str
    llm_config: Dict[str, Any]
    schema_paths: Optional[Dict[str, str]]

def create_agent(spec: AgentSpec, tools: Optional[List[Any]] = None) -> Runnable:
    """Unified factory that instantiates a LangChain Runnable agent from an AgentSpec."""
    prompt_template = get_prompt(spec["prompt_id"])
    
    # Format properties depending on requirements
    format_kwargs = {}
    schema_paths = spec.get("schema_paths") or {}
    
    if "SCHEMA" in prompt_template or "Examples" in spec["name"] or "Scorer" in spec["name"] or "CIO" in spec["name"]:
        # If schema is needed
        for placeholder, path in schema_paths.items():
            format_kwargs[placeholder] = read_file_content(path)
            
    if spec["name"] == "Sentiment_Scorer":
        format_kwargs["EXAMPLES"] = "Use the matching 'calibration_examples' list provided inline inside the user message for each article."
        
    if format_kwargs:
        # Pre-format the system prompt template with the schema structure/examples
        system_prompt = prompt_template.format(**format_kwargs)
    else:
        system_prompt = prompt_template

    system_prompt_escaped = system_prompt.replace("{", "{{").replace("}", "}}")
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt_escaped),
        ("human", "{input}")
    ])
    
    # Extract model and credentials from the AutoGen-style config
    config_list = spec["llm_config"].get("config_list", [])
    if config_list:
        cfg = config_list[0]
        model = cfg.get("model", spec["llm_config"].get("model"))
        base_url = cfg.get("base_url")
        api_key = cfg.get("api_key")
    else:
        model = spec["llm_config"].get("model")
        base_url = spec["llm_config"].get("base_url")
        api_key = spec["llm_config"].get("api_key")

    llm = build_chat_model(
        model=model,
        base_url=base_url,
        api_key=api_key
    )
    
    if tools:
        try:
            llm = llm.bind_tools(tools, parallel_tool_calls=False)
        except Exception:
            llm = llm.bind_tools(tools)
        
    return prompt | llm

# Retain original functions for backward compatibility using the factory internally
def create_scorer_agent(prompt_id: str, schema_path: str, llm_config: dict) -> Runnable:
    spec: AgentSpec = {
        "name": "Sentiment_Scorer",
        "description": "Scoration specialist agent.",
        "prompt_id": prompt_id,
        "llm_config": llm_config,
        "schema_paths": {"SCHEMA": schema_path}
    }
    return create_agent(spec)

def create_cio_agent(prompt_id: str, schema_path: str, output_schema_path: str, scored_articles_path: str, llm_config: dict, tools: Optional[List[Any]] = None) -> Runnable:
    spec: AgentSpec = {
        "name": "Senior_Sentiment_Analyst",
        "description": "Consolidation and aggregation agent.",
        "prompt_id": prompt_id,
        "llm_config": llm_config,
        "schema_paths": {
            "SCHEMA": schema_path,
            "EXAMPLES": scored_articles_path,
            "OUTPUT": output_schema_path
        }
    }
    return create_agent(spec, tools=tools)

def create_forexfactory_agent(prompt_id: str, schema_path: str, example_path: str, llm_config: dict, tools: Optional[List[Any]] = None) -> Runnable:
    spec: AgentSpec = {
        "name": "ForexFactory_Scraper_Agent",
        "description": "Specialist scraper that retrieves real-time calendar values for specific macroeconomic events.",
        "prompt_id": prompt_id,
        "llm_config": llm_config,
        "schema_paths": {
            "SCHEMA": schema_path,
            "EXAMPLES": example_path
        }
    }
    return create_agent(spec, tools=tools)

def create_alphavantage_agent(prompt_id: str, schema_path: str, example_path: str, llm_config: dict, tools: Optional[List[Any]] = None) -> Runnable:
    spec: AgentSpec = {
        "name": "AlphaVantage_Agent",
        "description": "Specialist in historical baselines and rolling standard deviation calculations.",
        "prompt_id": prompt_id,
        "llm_config": llm_config,
        "schema_paths": {
            "SCHEMA": schema_path,
            "EXAMPLES": example_path
        }
    }
    return create_agent(spec, tools=tools)

def create_macro_cio_agent(prompt_id: str, schema_path: str, example_path: str, llm_config: dict, tools: Optional[List[Any]] = None) -> Runnable:
    spec: AgentSpec = {
        "name": "Chief_Macro_Economist",
        "description": "Executive macro analyst that calculates final macro surprise scores and compiles JSON reports.",
        "prompt_id": prompt_id,
        "llm_config": llm_config,
        "schema_paths": {
            "SCHEMA": schema_path,
            "EXAMPLES": example_path
        }
    }
    return create_agent(spec, tools=tools)

def create_decomposition_agent(prompt_id: str, schema_path: str, example_path: str, llm_config: dict) -> Runnable:
    spec: AgentSpec = {
        "name": "Decomposition_Worker",
        "description": "Decomposition worker that decomposes the ETF into its constituent tickers and weights.",
        "prompt_id": prompt_id,
        "llm_config": llm_config,
        "schema_paths": {
            "SCHEMA": schema_path,
            "EXAMPLES": example_path
        }
    }
    return create_agent(spec)

def create_textual_inertia_agent(prompt_id: str, llm_config: dict) -> Runnable:
    spec: AgentSpec = {
        "name": "Textual_Inertia_Agent",
        "description": "Tracks text deviations between consecutive annual corporate filings (10-K).",
        "prompt_id": prompt_id,
        "llm_config": llm_config,
        "schema_paths": {}
    }
    return create_agent(spec)

def create_tension_extractor_agent(prompt_id: str, llm_config: dict) -> Runnable:
    spec: AgentSpec = {
        "name": "Tension_Extractor_Agent",
        "description": "Analyzes earnings call transcripts to trace signs of corporate tension and defensiveness.",
        "prompt_id": prompt_id,
        "llm_config": llm_config,
        "schema_paths": {}
    }
    return create_agent(spec)

def create_scribe_agent(prompt_id: str, llm_config: dict) -> Runnable:
    spec: AgentSpec = {
        "name": "Thesis_CoT_Scribe",
        "description": "Compliance documentarian that writes override narrative justifications for portfolio drifts.",
        "prompt_id": prompt_id,
        "llm_config": llm_config,
        "schema_paths": {}
    }
    return create_agent(spec)