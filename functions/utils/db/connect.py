import os
from pymongo import MongoClient

_client = None

def get_db_client():
    global _client
    if _client is None:
        mongodb_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        _client = MongoClient(
            mongodb_uri, 
            tlsAllowInvalidCertificates=True,
            maxIdleTimeMS=60000,
            socketTimeoutMS=600000,
            connectTimeoutMS=10000,
            serverSelectionTimeoutMS=10000
        )
    
    db_name = os.getenv("MONGODB_DB", "sentinel_db")
    return _client, _client[db_name]

def get_vector_collection():
    _, db = get_db_client()
    collection_name = os.getenv("MONGODB_CALIBRATION_COLLECTION", "calibration_embeddings")
    return db[collection_name]