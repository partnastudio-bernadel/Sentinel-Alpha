import os
import sys
import json
from typing import Dict, Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.store.base import BaseStore

script_dir = os.path.dirname(os.path.abspath(__file__))
sentiment_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))

if sentiment_dir not in sys.path:
    sys.path.insert(0, sentiment_dir)

from functions.types.macro_state import MacroState
from functions.utils.db.connect import get_db_client
from functions.nodes.forex_factory import forex_factory_node
from functions.nodes.alpha_vantage import alpha_vantage_node
from functions.nodes.textual_inertia import textual_inertia_node
from functions.nodes.tension_extractor import tension_extractor_node
from functions.nodes.chief_economist import chief_economist_node
from functions.nodes.governance import governor_node


def build_macro_graph():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sentiment_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))

    builder = StateGraph(MacroState)
    
    builder.add_node("forex_factory", forex_factory_node)
    builder.add_node("alpha_vantage", alpha_vantage_node)
    builder.add_node("textual_inertia", textual_inertia_node)
    builder.add_node("tension_extractor", tension_extractor_node)
    builder.add_node("chief_economist", chief_economist_node)
    builder.add_node("governance_node", governor_node)
    
    builder.add_edge(START, "forex_factory")
    builder.add_edge("forex_factory", "alpha_vantage")
    builder.add_edge("alpha_vantage", "textual_inertia")
    builder.add_edge("textual_inertia", "tension_extractor")
    builder.add_edge("tension_extractor", "chief_economist")
    builder.add_edge("chief_economist", "governance_node")
    builder.add_edge("governance_node", END)
    
    # Goal 1: Setup MongoDBSaver checkpointer and MongoDBStore
    from langgraph.checkpoint.mongodb import MongoDBSaver
    from langgraph.store.mongodb import MongoDBStore
    client, db = get_db_client()
    checkpointer = MongoDBSaver(client)
    store = MongoDBStore(db["langgraph_store"])
    
    return builder.compile(checkpointer=checkpointer, store=store)
