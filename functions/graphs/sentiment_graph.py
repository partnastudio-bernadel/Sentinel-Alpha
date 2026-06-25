import os
import sys
import time
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command

script_dir = os.path.dirname(os.path.abspath(__file__))
sentiment_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))

if sentiment_dir not in sys.path:
    sys.path.insert(0, sentiment_dir)

from functions.types.sentiment_state import SentimentState
from functions.utils.db.connect import get_db_client
from functions.nodes.ingest_news import ingest_news_node
from functions.nodes.check_cache import check_cache_node
from functions.nodes.sentiment_scorer import sentiment_scorer_node
from functions.nodes.cio_analyst import cio_analyst_node
from functions.nodes.governance import governor_node


# Router node to determine if we bypass caching or not
def route_scoring(state: SentimentState) -> str:
    if state.get("force_rescore", False):
        return "prepare_bypass"
    return "check_cache"


# Prepare bypass node: Inject cache buster timestamp to invalidate LangGraph's internal cache policy
def prepare_bypass_node(state: SentimentState) -> Command:
    return Command(
        goto="sentiment_scorer_node",
        update={"cache_buster": time.time()}
    )





def build_sentiment_graph():
    # Resolve project root dir context
    global sentiment_dir
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sentiment_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))

    builder = StateGraph(SentimentState)
    
    builder.add_node("ingest_news", ingest_news_node)
    builder.add_node("check_cache", check_cache_node)
    builder.add_node("prepare_bypass", prepare_bypass_node)
    builder.add_node("sentiment_scorer_node", sentiment_scorer_node)
    builder.add_node("cio_analyst_node", cio_analyst_node)
    builder.add_node("governance_node", governor_node)
    
    builder.add_edge(START, "ingest_news")
    builder.add_conditional_edges(
        "ingest_news",
        route_scoring,
        {
            "prepare_bypass": "prepare_bypass",
            "check_cache": "check_cache"
        }
    )
    builder.add_edge("check_cache", "sentiment_scorer_node")
    builder.add_edge("sentiment_scorer_node", "cio_analyst_node")
    builder.add_edge("cio_analyst_node", "governance_node")
    builder.add_edge("governance_node", END)
    
    # Goal 1: Add MongoDBStore to compilation alongside MongoDBSaver checkpointer
    from langgraph.checkpoint.mongodb import MongoDBSaver
    from langgraph.store.mongodb import MongoDBStore
    client, db = get_db_client()
    checkpointer = MongoDBSaver(client)
    store = MongoDBStore(db["langgraph_store"])
    
    return builder.compile(checkpointer=checkpointer, store=store)
