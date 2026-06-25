import os
from langchain_mongodb import MongoDBAtlasVectorSearch
from langchain_mongodb.agent_toolkit import MongoDBDatabaseToolkit, MongoDBDatabase
from langchain_core.tools import create_retriever_tool
from functions.utils.db.connect import get_db_client, get_vector_collection

def get_mongodb_toolkit(llm):
    """Initializes and returns the MongoDBDatabaseToolkit for agents to query historical sentiment data."""
    db_name = os.getenv("MONGODB_DB", "sentinel_db")
    
    # Use centralized connection and instantiate MongoDBDatabase directly
    client, _ = get_db_client()
    db = MongoDBDatabase(client=client, database=db_name)
    return MongoDBDatabaseToolkit(db=db, llm=llm)

def get_mongodb_retriever_tool(embeddings):
    """Creates a LangChain retriever tool wrapping MongoDBAtlasVectorSearch for calibration query RAG."""
    index_name = os.getenv("MONGODB_VECTOR_INDEX", "vector_index")
    
    # Use centralized vector collection helper
    collection = get_vector_collection()
    
    vector_store = MongoDBAtlasVectorSearch(
        collection=collection,
        embedding=embeddings,
        index_name=index_name,
        text_key="text",
        embedding_key="embedding"
    )
    
    retriever = vector_store.as_retriever(search_kwargs={"k": 2})
    
    retriever_tool = create_retriever_tool(
        retriever,
        name="retrieve_calibration_examples",
        description="Search for similar financial sentence calibration examples and their corresponding sentiment classifications."
    )
    return retriever_tool
