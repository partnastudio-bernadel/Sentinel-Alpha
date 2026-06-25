import os
from functions.utils.db.connect import get_db_client

_PROMPT_CACHE = {}

def get_prompt(prompt_id: str) -> str:
    """
    Fetches a prompt from MongoDB by its ID, with a startup in-memory cache.
    If the prompt is not in the cache, it fetches from DB and caches it.
    """
    global _PROMPT_CACHE
    
    if prompt_id in _PROMPT_CACHE:
        return _PROMPT_CACHE[prompt_id]
        
    client, db = get_db_client()
    prompts_collection = db["prompts"]
    
    doc = prompts_collection.find_one({"_id": prompt_id})
    if not doc or "content" not in doc:
        raise ValueError(f"Prompt '{prompt_id}' not found in MongoDB.")
        
    content = doc["content"]
    _PROMPT_CACHE[prompt_id] = content
    return content

def refresh_prompt_cache():
    """Forces a refresh of the in-memory prompt cache from MongoDB."""
    global _PROMPT_CACHE
    _PROMPT_CACHE.clear()
