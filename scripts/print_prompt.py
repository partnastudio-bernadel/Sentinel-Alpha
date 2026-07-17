import os
import sys
from dotenv import load_dotenv

script_dir = os.path.dirname(os.path.abspath(__file__))
sentiment_dir = os.path.dirname(script_dir)
if sentiment_dir not in sys.path:
    sys.path.insert(0, sentiment_dir)

from functions.utils.db.connect import get_db_client

load_dotenv(os.path.join(sentiment_dir, ".env.local"))
client, db = get_db_client()
doc = db["prompts"].find_one({"_id": "sentiment_scorer.txt"})
if doc:
    print("PROMPT CONTENT:")
    print(doc["content"])
else:
    print("Prompt not found")
