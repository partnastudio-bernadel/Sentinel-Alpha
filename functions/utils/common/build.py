import os
import pandas as pd
from langchain_mongodb import MongoDBAtlasVectorSearch
from langchain_core.documents import Document
from functions.utils.db.connect import get_vector_collection

def build_vector_store(csv_path, embeddings, limit_rows=300):
    """Loads historical sentiment CSV, processes and indexes records into MongoDB Atlas Vector Search."""
    print(f"Loading dataset: {csv_path}...")
    df = pd.read_csv(csv_path)
    df = df.dropna(subset=["Sentence", "Sentiment"])
    
    df_subset = df.head(limit_rows)
    
    index_name = os.getenv("MONGODB_VECTOR_INDEX", "vector_index")
    
    
    collection = get_vector_collection()
    
    # Check if we already have documents in the collection to avoid redundant embedding generations
    doc_count = collection.count_documents({})
    if doc_count >= len(df_subset):
        print(f"[CACHE HIT] Loaded pre-computed calibration embeddings from MongoDB collection.")
        db = MongoDBAtlasVectorSearch(
            collection=collection,
            embedding=embeddings,
            index_name=index_name,
            text_key="text",
            embedding_key="embedding"
        )
        return db
        
    print(f"[CACHE MISS] Generating calibration embeddings via NVIDIA API and saving to MongoDB collection'...")
    documents = [
        Document(page_content=row["Sentence"], metadata={"sentiment": row["Sentiment"]})
        for _, row in df_subset.iterrows()
    ]
    
    # Clear existing documents to re-populate cleanly
    collection.delete_many({})
    
    db = MongoDBAtlasVectorSearch.from_documents(
        documents=documents,
        embedding=embeddings,
        collection=collection,
        index_name=index_name,
        text_key="text",
        embedding_key="embedding"
    )
    print("[+] MongoDB Atlas Vector Store initialized and populated successfully!")
    return db